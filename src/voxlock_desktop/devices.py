"""Audio backends. Linux uses PulseAudio-compatible PipeWire; Windows uses PortAudio.

No virtual audio driver is installed on Windows. Install VB-CABLE separately and
select its CABLE Input playback endpoint as the app output.
"""
from __future__ import annotations

from dataclasses import dataclass
import platform
import shutil
import subprocess
from threading import Lock

import numpy as np
import soxr

SAMPLE_RATE = 16000
BLOCK = 640  # 40 ms at VoxLock's 16 kHz
SINK_NAME = "voxlock_desktop_sink"
SOURCE_NAME = "voxlock_desktop_mic"


@dataclass(frozen=True)
class Device:
    key: str
    label: str


def is_linux() -> bool:
    return platform.system() == "Linux"


def is_windows() -> bool:
    return platform.system() == "Windows"


def _pactl(*args: str) -> str:
    completed = subprocess.run(
        ["pactl", *args], capture_output=True, text=True, timeout=8, check=True
    )
    return completed.stdout.strip()


def list_inputs() -> list[Device]:
    if is_linux():
        if not shutil.which("pactl"):
            raise RuntimeError("pactl is missing. Install pulseaudio-utils.")
        sources = []
        for line in _pactl("list", "short", "sources").splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                parts = line.split()
            if len(parts) < 2:
                continue
            name = parts[1]
            if name.endswith(".monitor") or name == SOURCE_NAME:
                continue
            sources.append(Device(name, name))
        return sources
    if is_windows():
        return _windows_devices("input")
    raise RuntimeError("Supported operating systems: Linux and Windows.")


def list_outputs() -> list[Device]:
    if is_linux():
        return [Device(SINK_NAME, "VoxLock Microphone (PipeWire / PulseAudio)")]
    if is_windows():
        return _windows_devices("output")
    return []


def _windows_devices(direction: str) -> list[Device]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "Windows requires sounddevice. Run: pip install -e '.[windows]'"
        ) from exc
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    result = []
    for index, item in enumerate(devices):
        if item[f"max_{direction}_channels"] < 1:
            continue
        api = hostapis[item["hostapi"]]["name"]
        result.append(Device(str(index), f"{item['name']}  [{api}]"))
    return result


def _read_exact(pipe, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        piece = pipe.read(count - len(chunks))
        if not piece:
            raise RuntimeError("Microphone stream closed or was disconnected.")
        chunks.extend(piece)
    return bytes(chunks)


class LinuxSession:
    """16 kHz mono f32 PCM through parec/pacat and a private null sink."""

    def __init__(self, microphone: str, create_output: bool = True):
        self.microphone = microphone
        self.create_output = create_output
        self.modules: list[str] = []
        self.capture = None
        self.playback = None
        self.lock = Lock()

    def open(self) -> None:
        for command in ("pactl", "parec", "pacat"):
            if not shutil.which(command):
                raise RuntimeError(f"{command} is missing (install pulseaudio-utils).")
        try:
            if self.create_output:
                # Fail clearly rather than silently connect to a different app's sink.
                sinks = _pactl("list", "short", "sinks")
                if any(SINK_NAME in line for line in sinks.splitlines()):
                    raise RuntimeError(
                        f"{SINK_NAME} already exists. Remove stale modules or restart PipeWire."
                    )
                self.modules.append(_pactl(
                    "load-module", "module-null-sink",
                    f"sink_name={SINK_NAME}",
                    "sink_properties=device.description=VoxLock_Internal",
                ))
                self.modules.append(_pactl(
                    "load-module", "module-remap-source",
                    f"master={SINK_NAME}.monitor",
                    f"source_name={SOURCE_NAME}",
                    "source_properties=device.description=VoxLock_Microphone",
                ))
                self.playback = subprocess.Popen(
                    ["pacat", "--playback", "--raw", "--format=float32le",
                     "--rate=16000", "--channels=1", "--latency-msec=50", f"--device={SINK_NAME}"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, bufsize=0,
                )
            self.capture = subprocess.Popen(
                ["parec", "--record", "--raw", "--format=float32le",
                 "--rate=16000", "--channels=1", "--latency-msec=50", f"--device={self.microphone}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            )
        except Exception:
            self.close()
            raise

    def read(self) -> np.ndarray:
        if self.capture is None or self.capture.stdout is None:
            raise RuntimeError("Microphone capture was not started.")
        return np.frombuffer(_read_exact(self.capture.stdout, BLOCK * 4),
                             dtype="<f4").copy()

    def write(self, pcm: np.ndarray) -> None:
        if self.playback is None or self.playback.stdin is None:
            raise RuntimeError("Virtual microphone output was not started.")
        self.playback.stdin.write(np.asarray(pcm, dtype="<f4").tobytes())

    def abort_capture(self) -> None:
        with self.lock:
            if self.capture is not None and self.capture.poll() is None:
                self.capture.terminate()

    def close(self) -> None:
        with self.lock:
            procs = [self.capture, self.playback]
            self.capture = self.playback = None
        for proc in procs:
            if proc is None:
                continue
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except OSError:
                        pass
        for module in reversed(self.modules):
            try:
                _pactl("unload-module", module)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
        self.modules.clear()


class WindowsSession:
    """PortAudio capture/playback, continuously resampled to/from 16 kHz.

    The selected output must be a virtual cable playback endpoint (e.g. VB-CABLE
    'CABLE Input'). Apps then select its corresponding recording endpoint.
    """

    def __init__(self, microphone: str, output: str | None = None):
        self.microphone, self.output = int(microphone), (
            int(output) if output is not None else None
        )
        self.capture = None
        self.playback = None
        self.input_rate = 0
        self.output_rate = 0
        self.to_model = None
        self.from_model = None

    def open(self) -> None:
        import sounddevice as sd

        self.input_rate = int(round(sd.query_devices(self.microphone)["default_samplerate"])) or 48000
        self.to_model = soxr.ResampleStream(
            self.input_rate, SAMPLE_RATE, 1, dtype="float32", quality="LQ"
        ) if self.input_rate != SAMPLE_RATE else None
        try:
            self.capture = sd.RawInputStream(
                device=self.microphone, samplerate=self.input_rate, channels=1,
                dtype="float32", blocksize=int(round(self.input_rate * 0.04)),
            )
            self.capture.start()
            if self.output is not None:
                self.output_rate = int(round(sd.query_devices(self.output)["default_samplerate"])) or 48000
                self.from_model = soxr.ResampleStream(
                    SAMPLE_RATE, self.output_rate, 1, dtype="float32", quality="LQ"
                ) if self.output_rate != SAMPLE_RATE else None
                self.playback = sd.RawOutputStream(
                    device=self.output, samplerate=self.output_rate,
                    channels=1, dtype="float32",
                )
                self.playback.start()
        except Exception:
            self.close()
            raise

    def read(self) -> np.ndarray:
        frames = int(round(self.input_rate * 0.04))
        pcm, overflow = self.capture.read(frames)
        raw = np.frombuffer(pcm, dtype="<f4")
        return self.to_model.resample_chunk(raw) if self.to_model else raw.copy()

    def write(self, pcm: np.ndarray) -> None:
        if self.playback is None:
            raise RuntimeError("No virtual cable playback device selected.")
        data = self.from_model.resample_chunk(pcm) if self.from_model else pcm
        if len(data):
            self.playback.write(np.asarray(data, dtype="<f4").tobytes())

    def abort_capture(self) -> None:
        if self.capture:
            try:
                self.capture.abort()
            except Exception:
                pass

    def close(self) -> None:
        for stream in (self.capture, self.playback):
            if stream:
                try:
                    stream.abort()
                    stream.close()
                except Exception:
                    pass
        self.capture = self.playback = None


def make_session(microphone: str, output: str | None = None,
                 create_output: bool = True):
    if is_linux():
        return LinuxSession(microphone, create_output=create_output)
    if is_windows():
        return WindowsSession(microphone, output if create_output else None)
    raise RuntimeError("Only Linux and Windows are supported.")
