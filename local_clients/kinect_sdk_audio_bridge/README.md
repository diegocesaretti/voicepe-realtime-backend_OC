# Kinect SDK Audio Bridge

Experimental client for branch `kinect-sdk-audio`.

This bridge uses Microsoft Kinect SDK v1.8 directly instead of generic
PortAudio/sounddevice capture. Diego's PC has SDK v1.8 installed at:

```text
C:\Program Files\Microsoft SDKs\Kinect\v1.8
```

The goal is to evaluate whether SDK audio gives better far-field behavior than
the current Python PortAudio client.

## What It Uses

- `Microsoft.Kinect.KinectAudioSource`
- Adaptive SDK beam angle mode
- Kinect noise suppression
- Beam angle and sound-source angle change events
- 16 kHz mono PCM16 audio capture

## Build

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File local_clients\kinect_sdk_audio_bridge\build.ps1
```

## Probe

Capture 10 seconds to `data\kinect-sdk-probe.wav`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File local_clients\kinect_sdk_audio_bridge\probe.ps1
```

The probe writes angle metadata to stderr, for example:

```text
angle kind=source changed=0.123 confidence=0.870 beam=0.100 source=0.123 source_confidence=0.870
```

## Next Integration Step

Once probe audio is confirmed better than PortAudio, wire this bridge into the
existing Python client in one of two ways:

1. Run the bridge with `--stdout-pcm` and let Python read PCM16 from its stdout.
2. Promote the C# bridge to a full websocket client and keep Python only for
   openWakeWord if needed.

Do not replace `local_clients/kinect_windows_client.py` until the SDK path has
proved that beamforming improves Diego's room.

