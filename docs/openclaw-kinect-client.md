# OpenClaw Kinect Client

This fork keeps the original Voice PE backend architecture and adds a Windows
client path for Diego's Kinect mic array.

The goal is to replace only the physical Voice PE firmware client at first:

```text
Kinect on Windows -> local websocket client -> existing backend -> OpenAI Realtime
```

That preserves the backend's existing work for Realtime sessions, recovery,
phase handling, follow-up windows, enrollment, voice-printing, tool execution,
and audio capture.

## Current Client

`local_clients/kinect_windows_client.py` is a Python client that:

- opens the Kinect audio device on Windows;
- captures the Kinect's 4-channel 16 kHz PCM16 input;
- mixes it down to mono;
- sends binary PCM frames to the existing backend websocket;
- receives 24 kHz PCM16 reply audio from the backend and plays it locally;
- sends the same JSON control messages the backend already understands:
  `start`, `wake`, `interrupt`, and `ping`.

The backend already upsamples 16 kHz input to 24 kHz before OpenAI Realtime.

## Setup

From the repository root:

```powershell
python -m venv .venv-kinect
.venv-kinect\Scripts\python.exe -m pip install -r local_clients\requirements-windows-kinect.txt
```

List audio devices:

```powershell
.venv-kinect\Scripts\python.exe local_clients\kinect_windows_client.py --list-devices
```

On Diego's PC the Kinect was observed as:

- `Varios micrÃƒÂ³fonos (Kinect USB Audio)`
- WASAPI index varies by Windows boot/audio state; observed values include `9`
  and `14`
- 4 input channels
- 16 kHz default sample rate

Dry-run capture:

```powershell
.venv-kinect\Scripts\python.exe local_clients\kinect_windows_client.py --input-device Kinect --dry-run-audio --dry-run-seconds 5
```

Run against a backend already listening on `ws://127.0.0.1:8080/`:

```powershell
.venv-kinect\Scripts\python.exe local_clients\kinect_windows_client.py --input-device Kinect
```

Controls:

- Press `Enter` to send a `wake` event and open the mic.
- Type `s` then Enter to send `interrupt`.
- Type `q` then Enter to quit.

Wake-word mode uses openWakeWord locally on Windows and sends backend `wake`
only after the local detector fires:

```powershell
.venv-kinect\Scripts\python.exe local_clients\kinect_windows_client.py --input-device Kinect --wake-word
```

The default wake model is `hey_jarvis`. Default threshold is `0.39`, which is
about 30% more sensitive than the initial `0.55`; tune with `--wake-threshold`
if it is too eager or too deaf.

For continuous testing:

```powershell
.venv-kinect\Scripts\python.exe local_clients\kinect_windows_client.py --input-device Kinect --open-mic
```

## Next Adaptation Steps

1. Replace Home Assistant-only MCP assumptions with an OpenClaw tool bridge,
   while keeping a small Home Assistant allowlist for direct home controls.
2. Tune the Windows wake-word threshold for Diego's room and speaker placement.
3. Wire speaker enrollment storage to OpenClaw paths instead of Home Assistant
   add-on `/share` paths when running outside Home Assistant.
4. Add a Windows service or OpenClaw-managed process wrapper after the voice
   loop is stable.


