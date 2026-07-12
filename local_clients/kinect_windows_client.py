from __future__ import annotations

import argparse
import asyncio
import json
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets


DEFAULT_WS_URL = "ws://127.0.0.1:8080/"
DEFAULT_INPUT_SAMPLE_RATE = 16_000
BACKEND_OUTPUT_SAMPLE_RATE = 24_000
BLOCK_MS = 40


def list_devices() -> None:
    print(sd.query_devices())


def resolve_device(selector: str | None, *, input_device: bool) -> int | None:
    if selector is None or selector == "":
        return None
    try:
        return int(selector)
    except ValueError:
        pass

    needle = selector.lower()
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    matches: list[int] = []
    for idx, device in enumerate(devices):
        channels = device["max_input_channels"] if input_device else device["max_output_channels"]
        if channels > 0 and needle in str(device["name"]).lower():
            matches.append(idx)
    if matches:
        preferred_hostapi = "wasapi" if input_device else "mme"
        for idx in matches:
            hostapi_name = str(hostapis[int(devices[idx]["hostapi"])]["name"]).lower()
            if preferred_hostapi in hostapi_name:
                return idx
        return matches[0]
    kind = "input" if input_device else "output"
    raise SystemExit(f"No {kind} device matched {selector!r}. Use --list-devices.")


def default_input_channels(input_device: int | None) -> int:
    if input_device is None:
        input_device = sd.default.device[0]
    device = sd.query_devices(input_device, "input")
    return max(1, int(device["max_input_channels"]))


def pcm16_mono_bytes(indata: np.ndarray) -> bytes:
    if indata.ndim == 2 and indata.shape[1] > 1:
        if indata.dtype == np.int16:
            mono = np.mean(indata.astype(np.float32), axis=1)
            return np.clip(mono, -32768, 32767).astype(np.int16).tobytes()
        indata = np.mean(indata, axis=1, keepdims=True)
    if indata.dtype == np.int16:
        return indata.reshape(-1).tobytes()
    clipped = np.clip(indata.reshape(-1), -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


@dataclass
class ClientState:
    mic_open: bool
    continuous: bool = False
    enrolling: bool = False
    quit_requested: bool = False
    phase: str = "idle"
    reply_seen: bool = False
    follow_up_ms: int = 0
    follow_up_open_delay_ms: int = 0


class AudioIO:
    def __init__(
        self,
        input_device: int | None,
        output_device: int | None,
        input_sample_rate: int,
        input_channels: int,
        input_backend: str = "portaudio",
        sdk_bridge_exe: str | None = None,
    ):
        self.input_device = input_device
        self.output_device = output_device
        self.input_sample_rate = input_sample_rate
        self.input_channels = input_channels
        self.input_backend = input_backend
        self.sdk_bridge_exe = sdk_bridge_exe
        self.input_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self.wake_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self.output_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._output_buffer = bytearray()
        self._closed = threading.Event()
        self.input_stream: sd.InputStream | None = None
        self.output_stream: sd.OutputStream | None = None
        self.sdk_process: subprocess.Popen[bytes] | None = None
        self._sdk_threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.input_backend == "kinect-sdk":
            self._start_sdk_input()
        else:
            self.input_stream = sd.InputStream(
                samplerate=self.input_sample_rate,
                blocksize=int(self.input_sample_rate * BLOCK_MS / 1000),
                channels=self.input_channels,
                dtype="int16",
                device=self.input_device,
                callback=self._input_callback,
            )
            self.input_stream.start()
        self.output_stream = sd.OutputStream(
            samplerate=BACKEND_OUTPUT_SAMPLE_RATE,
            blocksize=int(BACKEND_OUTPUT_SAMPLE_RATE * BLOCK_MS / 1000),
            channels=1,
            dtype="int16",
            device=self.output_device,
            callback=self._output_callback,
        )
        self.output_stream.start()

    def close(self) -> None:
        self._closed.set()
        for stream in (self.input_stream, self.output_stream):
            if stream:
                stream.stop()
                stream.close()
        if self.sdk_process:
            self.sdk_process.terminate()
            try:
                self.sdk_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.sdk_process.kill()
            self.sdk_process = None

    def clear_output(self) -> None:
        while True:
            try:
                self.output_queue.get_nowait()
            except queue.Empty:
                break
        self._output_buffer.clear()

    def enqueue_tone(self, frequency_hz: float, duration_ms: int, volume: float = 0.6) -> None:
        frames = max(1, int(BACKEND_OUTPUT_SAMPLE_RATE * duration_ms / 1000))
        t = np.arange(frames, dtype=np.float32) / BACKEND_OUTPUT_SAMPLE_RATE
        tone = np.sin(2.0 * np.pi * frequency_hz * t)
        pcm = np.clip(tone * 32767.0 * volume, -32768, 32767).astype(np.int16).tobytes()
        try:
            self.output_queue.put_nowait(pcm)
        except queue.Full:
            pass

    def _input_callback(self, indata, _frame_count, _time_info, status) -> None:
        if status:
            print(f"input status: {status}", file=sys.stderr)
        if self._closed.is_set():
            return
        pcm = pcm16_mono_bytes(indata)
        self._enqueue_input_pcm(pcm)

    def _enqueue_input_pcm(self, pcm: bytes) -> None:
        try:
            self.input_queue.put_nowait(pcm)
        except queue.Full:
            pass
        try:
            self.wake_queue.put_nowait(pcm)
        except queue.Full:
            pass

    def _start_sdk_input(self) -> None:
        if not self.sdk_bridge_exe:
            raise RuntimeError("sdk_bridge_exe is required for kinect-sdk input")
        exe = Path(self.sdk_bridge_exe)
        if not exe.exists():
            raise RuntimeError(f"Kinect SDK bridge not found: {exe}")
        self.sdk_process = subprocess.Popen(
            [str(exe), "--stdout-pcm", "--probe-seconds", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        read_size = int(self.input_sample_rate * BLOCK_MS / 1000) * 2
        reader = threading.Thread(target=self._sdk_stdout_reader, args=(read_size,), daemon=True)
        err_reader = threading.Thread(target=self._sdk_stderr_reader, daemon=True)
        reader.start()
        err_reader.start()
        self._sdk_threads.extend([reader, err_reader])

    def _sdk_stdout_reader(self, read_size: int) -> None:
        assert self.sdk_process is not None and self.sdk_process.stdout is not None
        while not self._closed.is_set():
            chunk = self.sdk_process.stdout.read(read_size)
            if not chunk:
                if self.sdk_process.poll() is not None:
                    print(f"Kinect SDK bridge exited with {self.sdk_process.returncode}", file=sys.stderr)
                    return
                time.sleep(0.01)
                continue
            self._enqueue_input_pcm(chunk)

    def _sdk_stderr_reader(self) -> None:
        assert self.sdk_process is not None and self.sdk_process.stderr is not None
        while not self._closed.is_set():
            line = self.sdk_process.stderr.readline()
            if not line:
                if self.sdk_process.poll() is not None:
                    return
                time.sleep(0.05)
                continue
            try:
                print(f"sdk: {line.decode(errors='replace').rstrip()}", file=sys.stderr)
            except Exception:
                pass

    def _output_callback(self, outdata, frame_count, _time_info, status) -> None:
        if status:
            print(f"output status: {status}", file=sys.stderr)
        need_bytes = frame_count * 2
        while len(self._output_buffer) < need_bytes:
            try:
                self._output_buffer.extend(self.output_queue.get_nowait())
            except queue.Empty:
                break
        chunk = self._output_buffer[:need_bytes]
        del self._output_buffer[:need_bytes]
        if len(chunk) < need_bytes:
            chunk += b"\x00" * (need_bytes - len(chunk))
        outdata[:] = np.frombuffer(chunk, dtype=np.int16).reshape(frame_count, 1)


async def send_json(ws, payload: dict) -> None:
    await ws.send(json.dumps(payload, separators=(",", ":")))


async def audio_sender(ws, audio: AudioIO, state: ClientState, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            chunk = await asyncio.to_thread(audio.input_queue.get, True, 0.1)
        except queue.Empty:
            continue
        if state.mic_open:
            await ws.send(chunk)


async def follow_up_window(state: ClientState) -> None:
    if state.follow_up_open_delay_ms > 0:
        await asyncio.sleep(state.follow_up_open_delay_ms / 1000)
    if state.quit_requested or state.phase != "idle" or state.enrolling:
        return
    state.mic_open = True
    print("follow-up listening...")
    await asyncio.sleep(state.follow_up_ms / 1000)
    if state.phase == "idle" and not state.continuous:
        state.mic_open = False
        print("follow-up closed")


async def receiver(ws, audio: AudioIO, state: ClientState, stop_event: asyncio.Event, args) -> None:
    async for message in ws:
        if isinstance(message, bytes):
            try:
                audio.output_queue.put_nowait(message)
            except queue.Full:
                pass
            continue

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            print(f"backend text: {message}")
            continue

        msg_type = data.get("type")
        if msg_type == "hello":
            if args.follow_up_ms is not None:
                state.follow_up_ms = max(0, args.follow_up_ms)
            else:
                state.follow_up_ms = max(0, int(data.get("follow_up_ms") or 0))
            if args.follow_up_open_delay_ms is not None:
                state.follow_up_open_delay_ms = max(0, args.follow_up_open_delay_ms)
            else:
                state.follow_up_open_delay_ms = max(0, int(data.get("follow_up_open_delay_ms") or 0))
            print(f"backend hello: {data}")
        elif msg_type == "phase":
            phase = data.get("value")
            state.phase = str(phase)
            print(f"phase: {phase}")
            if phase in {"thinking", "replying"} and not state.enrolling:
                state.mic_open = False
            if phase == "replying":
                state.reply_seen = True
                audio.clear_output()
            if phase == "idle" and not state.quit_requested:
                if state.enrolling:
                    state.mic_open = True
                elif state.continuous:
                    state.mic_open = True
                elif state.reply_seen and state.follow_up_ms > 0 and not args.no_follow_up:
                    state.reply_seen = False
                    asyncio.create_task(follow_up_window(state))
                else:
                    state.mic_open = False
        elif msg_type == "enroll":
            mode = data.get("mode")
            print(f"enroll mode: {mode}")
            if mode == "start":
                state.enrolling = True
                state.mic_open = True
                state.reply_seen = False
                audio.clear_output()
            elif mode == "stop":
                state.enrolling = False
                state.mic_open = state.continuous
        elif msg_type == "pong":
            pass
        elif msg_type == "ack":
            pass
        else:
            print(f"backend json: {data}")
    stop_event.set()


async def trigger_wake(ws, audio: AudioIO, state: ClientState, args) -> None:
    if state.enrolling:
        return
    state.mic_open = False
    audio.clear_output()
    if state.phase == "replying":
        await send_json(ws, {"type": "interrupt"})
    if args.wake_sound:
        audio.enqueue_tone(args.wake_sound_frequency, args.wake_sound_ms)
    await send_json(ws, {"type": "wake"})
    if args.wake_open_delay_ms > 0:
        await asyncio.sleep(args.wake_open_delay_ms / 1000)
    state.mic_open = True


async def keyboard_loop(ws, audio: AudioIO, state: ClientState, stop_event: asyncio.Event, args) -> None:
    if args.open_mic:
        await trigger_wake(ws, audio, state, args)
        print("Open mic mode. Press Ctrl+C to stop.")
        while not stop_event.is_set():
            await asyncio.sleep(0.5)
        return

    print("Press Enter to wake/listen, s + Enter to stop reply, q + Enter to quit.")
    while not stop_event.is_set():
        line = await asyncio.to_thread(sys.stdin.readline)
        command = line.strip().lower()
        if command == "q":
            state.quit_requested = True
            stop_event.set()
            return
        if command == "s":
            audio.clear_output()
            await send_json(ws, {"type": "interrupt"})
            continue
        await trigger_wake(ws, audio, state, args)
        print("listening...")


def ensure_wake_model(model_name: str, inference_framework: str) -> None:
    import openwakeword
    from openwakeword.utils import download_models

    model_info = openwakeword.MODELS.get(model_name)
    if not model_info:
        return
    model_path = Path(model_info["model_path"])
    if inference_framework == "onnx":
        model_path = model_path.with_suffix(".onnx")
    if not model_path.exists():
        print(f"Downloading wake model {model_name}...")
        download_models([model_name])


async def wake_word_loop(ws, audio: AudioIO, state: ClientState, stop_event: asyncio.Event, args) -> None:
    from openwakeword.model import Model

    ensure_wake_model(args.wake_model, args.wake_inference_framework)
    model = await asyncio.to_thread(
        Model,
        wakeword_models=[args.wake_model],
        inference_framework=args.wake_inference_framework,
    )
    last_wake = 0.0
    print(
        f"Wake-word mode: say '{args.wake_phrase}' "
        f"(model={args.wake_model}, threshold={args.wake_threshold})"
    )
    while not stop_event.is_set():
        try:
            chunk = await asyncio.to_thread(audio.wake_queue.get, True, 0.1)
        except queue.Empty:
            continue
        if state.enrolling:
            continue
        samples = np.frombuffer(chunk, dtype=np.int16)
        scores = await asyncio.to_thread(model.predict, samples)
        score = max((float(v) for v in scores.values()), default=0.0)
        now = time.monotonic()
        if score >= args.wake_threshold and now - last_wake >= args.wake_cooldown_seconds:
            last_wake = now
            if not state.mic_open:
                await trigger_wake(ws, audio, state, args)
                print(f"wake detected ({score:.2f}); listening...")


async def ping_loop(ws, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(20)
        try:
            await send_json(ws, {"type": "ping"})
        except Exception:
            stop_event.set()


async def run_client(args) -> None:
    input_device = None if args.input_backend == "kinect-sdk" else resolve_device(args.input_device, input_device=True)
    output_device = resolve_device(args.output_device, input_device=False)
    input_channels = 1 if args.input_backend == "kinect-sdk" else (args.input_channels or default_input_channels(input_device))
    sdk_bridge_exe = args.sdk_bridge_exe
    if args.input_backend == "kinect-sdk" and not sdk_bridge_exe:
        sdk_bridge_exe = str(
            Path(__file__).resolve().parent
            / "kinect_sdk_audio_bridge"
            / "bin"
            / "OpenClaw.KinectSdkAudioBridge.exe"
        )
    audio = AudioIO(
        input_device=input_device,
        output_device=output_device,
        input_sample_rate=args.input_sample_rate,
        input_channels=input_channels,
        input_backend=args.input_backend,
        sdk_bridge_exe=sdk_bridge_exe,
    )
    state = ClientState(mic_open=args.open_mic, continuous=args.open_mic)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    print(
        f"Connecting to {args.ws_url} with input_backend={args.input_backend}, input_device={input_device}, "
        f"input_channels={input_channels}, input_rate={args.input_sample_rate}"
    )
    async with websockets.connect(args.ws_url, max_size=16 * 1024 * 1024) as ws:
        audio.start()
        await send_json(ws, {"type": "start", "client": "openclaw-kinect-windows"})
        try:
            tasks = [
                audio_sender(ws, audio, state, stop_event),
                receiver(ws, audio, state, stop_event, args),
                ping_loop(ws, stop_event),
            ]
            if args.wake_word:
                tasks.append(wake_word_loop(ws, audio, state, stop_event, args))
            else:
                tasks.append(keyboard_loop(ws, audio, state, stop_event, args))
            await asyncio.gather(*tasks)
        finally:
            audio.close()


async def dry_run_audio(args) -> None:
    if args.input_backend == "kinect-sdk":
        sdk_bridge_exe = args.sdk_bridge_exe or str(
            Path(__file__).resolve().parent
            / "kinect_sdk_audio_bridge"
            / "bin"
            / "OpenClaw.KinectSdkAudioBridge.exe"
        )
        audio = AudioIO(
            input_device=None,
            output_device=None,
            input_sample_rate=args.input_sample_rate,
            input_channels=1,
            input_backend="kinect-sdk",
            sdk_bridge_exe=sdk_bridge_exe,
        )
        frames = 0
        started = time.monotonic()
        audio.start()
        try:
            print(f"Capturing Kinect SDK input via {sdk_bridge_exe}. Press Ctrl+C to stop.", flush=True)
            while True:
                try:
                    chunk = await asyncio.to_thread(audio.input_queue.get, True, 1.0)
                    frames += len(chunk) // 2
                except queue.Empty:
                    pass
                elapsed = max(0.001, time.monotonic() - started)
                print(f"received {frames} frames ({frames / elapsed:.0f} frames/sec)", flush=True)
                if args.dry_run_seconds and elapsed >= args.dry_run_seconds:
                    return
        finally:
            audio.close()

    input_device = resolve_device(args.input_device, input_device=True)
    input_channels = args.input_channels or default_input_channels(input_device)
    frames = 0
    started = time.monotonic()

    def callback(indata, frame_count, _time_info, status) -> None:
        nonlocal frames
        if status:
            print(f"audio status: {status}", file=sys.stderr)
        _ = pcm16_mono_bytes(indata)
        frames += frame_count

    print(
        f"Capturing input_device={input_device}, channels={input_channels}, "
        f"rate={args.input_sample_rate}. Press Ctrl+C to stop.",
        flush=True,
    )
    with sd.InputStream(
        samplerate=args.input_sample_rate,
        blocksize=int(args.input_sample_rate * BLOCK_MS / 1000),
        channels=input_channels,
        dtype="int16",
        device=input_device,
        callback=callback,
    ):
        while True:
            await asyncio.sleep(1)
            elapsed = max(0.001, time.monotonic() - started)
            print(f"received {frames} frames ({frames / elapsed:.0f} frames/sec)", flush=True)
            if args.dry_run_seconds and elapsed >= args.dry_run_seconds:
                return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows Kinect client for the Voice PE Realtime backend")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--dry-run-audio", action="store_true")
    parser.add_argument("--dry-run-seconds", type=float)
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL)
    parser.add_argument("--input-backend", choices=("portaudio", "kinect-sdk"), default="portaudio")
    parser.add_argument("--sdk-bridge-exe", help="Path to OpenClaw.KinectSdkAudioBridge.exe")
    parser.add_argument("--input-device", default="Kinect")
    parser.add_argument("--output-device")
    parser.add_argument("--input-sample-rate", type=int, default=DEFAULT_INPUT_SAMPLE_RATE)
    parser.add_argument("--input-channels", type=int, default=0, help="Default: device max")
    parser.add_argument("--open-mic", action="store_true", help="Stream continuously after connection")
    parser.add_argument("--wake-word", action="store_true", help="Use local openWakeWord detection before streaming")
    parser.add_argument("--wake-model", default="hey_jarvis")
    parser.add_argument("--wake-phrase", default="hey jarvis")
    parser.add_argument("--wake-threshold", type=float, default=0.39)
    parser.add_argument("--wake-cooldown-seconds", type=float, default=2.0)
    parser.add_argument("--wake-inference-framework", choices=("onnx", "tflite"), default="onnx")
    parser.add_argument("--wake-sound", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--wake-sound-frequency", type=float, default=880.0)
    parser.add_argument("--wake-sound-ms", type=int, default=120)
    parser.add_argument("--wake-open-delay-ms", type=int, default=700)
    parser.add_argument("--follow-up-ms", type=int, default=None, help="Default: backend hello follow_up_ms")
    parser.add_argument(
        "--follow-up-open-delay-ms",
        type=int,
        default=None,
        help="Default: backend hello follow_up_open_delay_ms",
    )
    parser.add_argument("--no-follow-up", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_devices:
        list_devices()
        return
    if args.dry_run_audio:
        asyncio.run(dry_run_audio(args))
        return
    asyncio.run(run_client(args))


if __name__ == "__main__":
    main()






