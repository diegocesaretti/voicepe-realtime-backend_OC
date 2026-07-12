# OpenClaw Kinect Stabilization Notes

Current stable path:

```text
Kinect USB Audio -> local_clients/kinect_windows_client.py -> backend websocket -> OpenAI Realtime -> Windows speakers
```

## Verified

- Backend starts on `127.0.0.1:8080` through `scripts/run_backend_windows.ps1`.
- Kinect client starts through `scripts/run_kinect_client_windows.ps1`.
- Windows auto-start task `OpenClaw Kinect Voice` runs `scripts/start_kinect_voice_windows.ps1`.
- Startup wrapper stops stale backend/client processes, waits for port `8080`, then starts the Kinect client.
- Wake word is `hey jarvis` with threshold `0.39`.
- Wake confirmation tone is enabled and lengthened to `220 ms`.
- Audio output is pinned to `--output-device Altavoces`, resolving to MME output on Diego's PC because the WASAPI JBL output rejected direct 24 kHz playback.
- Voice enrollment generated a usable Diego sample and `data/voice-prints/diego.json`.
- OpenClaw/Home Assistant tools are registered, but Home Assistant must be reachable for HA commands to succeed.

## Fragile Points

- The current PortAudio client captures the Kinect as a generic 4-channel microphone and mixes channels to mono. It does not use Kinect SDK beamforming metadata.
- Output device names can change when Windows audio devices are disconnected or renamed. The current selector intentionally prefers MME for output and WASAPI for input.
- Wake sensitivity `0.39` is useful for Diego's tests but may be too sensitive in a noisy room.
- Follow-up windows can capture short/noisy fragments if people talk near the speakers after a reply.
- The local git checkout may show files as modified when updates were made through the GitHub connector; the remote PR branch is the source of truth.

## Next Stabilization Work

- Add periodic health checks for backend websocket, client connection, and latest wake/audio activity.
- Add a short local audio self-test command that plays the same tone through the configured output device.
- Add client-side metrics for output bytes received and played, so "answered but no sound" is obvious in logs.
- Consider a fixed speaker output configuration for Cocina later, either Windows Bluetooth output or a cast/TTS path.
- Keep the SDK beamforming experiment on a separate branch until it proves better than the current PortAudio path.

