# Kinect Wake Vision Context

Goal: capture a Kinect RGB snapshot at wake time, summarize it with a vision
model, and inject the summary as short system context for the current voice turn.

## Current Prompt

The Windows backend wrapper sets:

```text
Sos Jarvis, asistente personal y de BWA 3D de Diego. HablÃ¡ en espaÃ±ol rioplatense, breve y natural. PodÃ©s ayudar con OpenClaw y controlar Home Assistant usando solo tools seguras.
```

The backend can also inject dynamic system messages into the Realtime
conversation. Speaker identification already uses that pattern in
`websocket_handler.py`; wake vision context should use the same mechanism.

## Implemented So Far

Branch `kinect-sdk-audio`:

- `OpenClaw.KinectSdkAudioBridge.exe` can enable Kinect SDK v1.8 RGB capture.
- `--snapshot-dir <path>` writes a rolling `latest.jpg`.
- `scripts/run_kinect_sdk_client_windows.ps1` writes snapshots to:

```text
data\kinect-sdk-snapshots\latest.jpg
```

The snapshot was visually validated on 2026-07-12 and showed the workspace.

## Target Flow

```text
Wake word detected
  -> copy latest Kinect RGB frame to a wake-specific snapshot path
  -> analyze snapshot with Gemini / Home Assistant LLM Vision
  -> inject a short text system message:
     "Visual context at wake: one person near the desk, room lights on..."
  -> user audio reaches Realtime as usual
```

## Gemini / Home Assistant Options

Preferred options, in order:

1. Direct Gemini API call from the backend using a local secret file.
   - Lowest latency.
   - Does not depend on Home Assistant file paths.
   - Needs a local Google API key secret, not committed.

2. Home Assistant `llmvision.image_analyzer`.
   - Reuses Diego's existing HA/Gemini setup.
   - Requires the Kinect snapshot to be visible to Home Assistant as either:
     - a local HA `image_file` path such as `/media/llmvision/snapshots/...`, or
     - an HA image/camera entity.
   - Current HA service schema exposes `image_file` and `image_entity`, not a
     simple arbitrary URL field.

## Context Prompt Rule

Keep injected visual summaries short and factual. Do not let the assistant
announce the visual context unless it is relevant to the user's request.

Suggested injected text:

```text
[wake visual context] A Kinect snapshot taken at wake time shows: {summary}.
Use this only if relevant. Do not mention the camera unless useful.
```

## Next Build Step

Add Python client wake hook:

- on wake, copy `data\kinect-sdk-snapshots\latest.jpg` to
  `data\kinect-wake-snapshots\wake_<timestamp>.jpg`;
- send a JSON control message to the backend with the snapshot path;
- backend analyzes it asynchronously and injects the summary as a system item.

The current production path should remain audio-only until snapshot analysis is
fast and reliable.

