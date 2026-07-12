"""Small OpenClaw-oriented tool bridge for the Realtime backend.

This is deliberately narrow. The voice model gets useful local/home controls,
not arbitrary shell access.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib import error, request

if TYPE_CHECKING:
    from pipecat.services.llm_service import FunctionCallParams


logger = logging.getLogger(__name__)

SAFE_HA_SERVICES: set[tuple[str, str]] = {
    ("light", "turn_on"),
    ("light", "turn_off"),
    ("switch", "turn_on"),
    ("switch", "turn_off"),
    ("climate", "set_temperature"),
    ("climate", "set_hvac_mode"),
    ("media_player", "turn_on"),
    ("media_player", "turn_off"),
    ("media_player", "media_play_pause"),
    ("media_player", "volume_set"),
    ("remote", "send_command"),
}


def _workspace() -> Path:
    return Path(os.environ.get("OPENCLAW_WORKSPACE", r"C:\Users\diego\.openclaw\workspace"))


def _ha_secret_path() -> Path:
    return Path(os.environ.get("HOMEASSISTANT_SECRET_PATH", r"C:\Users\diego\.openclaw\secrets\homeassistant.json"))


def _load_ha_config() -> dict[str, str]:
    secret = _ha_secret_path()
    if secret.exists():
        with secret.open("r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        if cfg.get("url") and cfg.get("token"):
            return {"url": cfg["url"], "token": cfg["token"]}

    url = os.environ.get("HOME_ASSISTANT_URL") or os.environ.get("HA_URL")
    token = os.environ.get("HOME_ASSISTANT_TOKEN") or os.environ.get("SUPERVISOR_TOKEN")
    if url and token:
        return {"url": url, "token": token}
    raise RuntimeError("Home Assistant URL/token not configured")


def _ha_request(method: str, path: str, data: dict[str, Any] | None = None) -> Any:
    cfg = _load_ha_config()
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = request.Request(
        cfg["url"].rstrip("/") + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {cfg['token']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Home Assistant HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Home Assistant connection failed: {exc.reason}") from exc


def get_openclaw_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "openclaw_status",
            "description": "Read local OpenClaw voice backend status and configured capabilities.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "ha_get_state",
            "description": "Read one Home Assistant entity state by entity_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Home Assistant entity id, for example climate.aire_cocina.",
                    }
                },
                "required": ["entity_id"],
            },
        },
        {
            "type": "function",
            "name": "ha_search_entities",
            "description": "Search Home Assistant entities by id or friendly name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text, for example cocina."},
                    "limit": {"type": "integer", "description": "Maximum results.", "default": 12},
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": "ha_call_safe_service",
            "description": "Call an allowlisted simple Home Assistant service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Service domain."},
                    "service": {"type": "string", "description": "Service name."},
                    "entity_id": {"type": "string", "description": "Target entity id."},
                    "data": {
                        "type": "object",
                        "description": "Extra JSON service data.",
                        "additionalProperties": True,
                    },
                },
                "required": ["domain", "service", "entity_id"],
            },
        },
    ]


def register_openclaw_tools(llm) -> None:
    async def _status(params: "FunctionCallParams") -> None:
        data = {
            "workspace": str(_workspace()),
            "ha_secret_present": _ha_secret_path().exists(),
            "safe_ha_services": sorted(f"{domain}.{service}" for domain, service in SAFE_HA_SERVICES),
        }
        await params.result_callback({"ok": True, "data": data})

    async def _ha_get_state(params: "FunctionCallParams") -> None:
        args = params.arguments or {}
        entity_id = str(args.get("entity_id", "")).strip()
        if not entity_id:
            await params.result_callback({"ok": False, "error": "entity_id is required"})
            return
        try:
            await params.result_callback({"ok": True, "data": _ha_request("GET", f"/api/states/{entity_id}")})
        except Exception as exc:
            logger.warning("ha_get_state failed: %r", exc)
            await params.result_callback({"ok": False, "error": str(exc)})

    async def _ha_search_entities(params: "FunctionCallParams") -> None:
        args = params.arguments or {}
        query = str(args.get("query", "")).strip().lower()
        limit = max(1, min(int(args.get("limit", 12) or 12), 25))
        if not query:
            await params.result_callback({"ok": False, "error": "query is required"})
            return
        try:
            states = _ha_request("GET", "/api/states")
            matches = []
            for item in states:
                entity_id = item.get("entity_id", "")
                friendly = item.get("attributes", {}).get("friendly_name", "")
                if query in f"{entity_id} {friendly}".lower():
                    matches.append(
                        {
                            "entity_id": entity_id,
                            "state": item.get("state"),
                            "friendly_name": friendly,
                        }
                    )
                    if len(matches) >= limit:
                        break
            await params.result_callback({"ok": True, "data": matches})
        except Exception as exc:
            logger.warning("ha_search_entities failed: %r", exc)
            await params.result_callback({"ok": False, "error": str(exc)})

    async def _ha_call_safe_service(params: "FunctionCallParams") -> None:
        args = params.arguments or {}
        domain = str(args.get("domain", "")).strip()
        service = str(args.get("service", "")).strip()
        entity_id = str(args.get("entity_id", "")).strip()
        data = args.get("data") or {}
        if (domain, service) not in SAFE_HA_SERVICES:
            await params.result_callback({"ok": False, "error": f"{domain}.{service} is not allowlisted"})
            return
        if not entity_id:
            await params.result_callback({"ok": False, "error": "entity_id is required"})
            return
        if not isinstance(data, dict):
            await params.result_callback({"ok": False, "error": "data must be an object"})
            return
        payload = dict(data)
        payload["entity_id"] = entity_id
        try:
            await params.result_callback(
                {"ok": True, "data": _ha_request("POST", f"/api/services/{domain}/{service}", payload)}
            )
        except Exception as exc:
            logger.warning("ha_call_safe_service failed: %r", exc)
            await params.result_callback({"ok": False, "error": str(exc)})

    llm.register_function("openclaw_status", _status)
    llm.register_function("ha_get_state", _ha_get_state)
    llm.register_function("ha_search_entities", _ha_search_entities)
    llm.register_function("ha_call_safe_service", _ha_call_safe_service)
