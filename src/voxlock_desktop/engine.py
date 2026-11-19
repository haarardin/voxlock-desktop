"""Audio worker threads. No microphone audio is sent to an external service.

During isolation, the virtual mic only receives model output or silence. If
inference or capture fails, processing stops rather than exposing raw speech.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
import os
import platform
import threading
import time

import numpy as np
import soundfile as sf
from PySide6.QtCore import QThread, Signal

from .devices import BLOCK, SAMPLE_RATE, make_session


def data_directory() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return base / "VoxLockDesktop"
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "voxlock-desktop"


def profile_file() -> Path:
    return data_directory() / "profiles" / "my_voice.wav"


def level_db(samples: np.ndarray) -> float:
    if len(samples) == 0:
        return -80.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return max(-80.0, 20.0 * np.log10(max(1e-8, rms)))


class AudioFIFO:
    """Bounded 16 kHz PCM FIFO: overflow discards oldest, underflow is silence."""

    def __init__(self, max_samples: int = SAMPLE_RATE):
        self.max_samples = max_samples
        self.lock = threading.Lock()
        self.chunks: deque[np.ndarray] = deque()
        self.size = 0
        self.dropped = 0

    def push(self, data: np.ndarray) -> None:
        x = np.asarray(data, dtype=np.float32).reshape(-1).copy()
        if not len(x):
            return
        if len(x) > self.max_samples:
            self.dropped += len(x) - self.max_samples
            x = x[-self.max_samples:]
        with self.lock:
            self.chunks.append(x)
            self.size += len(x)
            while self.size > self.max_samples:
                old = self.chunks.popleft()
                self.size -= len(old)
                self.dropped += len(old)

    def pop(self, count: int) -> np.ndarray:
        out = np.zeros(count, dtype=np.float32)
        with self.lock:
            pos = 0
            while pos < count and self.chunks:
                front = self.chunks[0]
                n = min(count - pos, len(front))
                out[pos:pos + n] = front[:n]
                pos += n
                self.size -= n
                if n == len(front):
                    self.chunks.popleft()
                else:
                    self.chunks[0] = front[n:]
        return out


class EnrollmentWorker(QThread):
    progress = Signal(int)
    success = Signal(str)
    failure = Signal(str)

    def __init__(self, microphone: str, duration: int = 8, parent=None):
        super().__init__(parent)
        self.microphone = microphone
        self.duration = duration
        self.cancelled = threading.Event()
        self.session = None

    def cancel(self):
        self.cancelled.set()
        if self.session:
            self.session.abort_capture()

    def run(self):
        samples = []
        try:
            self.session = make_session(self.microphone, create_output=False)
            self.session.open()
            for frame in range(int(self.duration * SAMPLE_RATE / BLOCK)):
                if self.cancelled.is_set():
                    return
                samples.append(self.session.read())
                if frame % 5 == 0:
                    self.progress.emit(min(100, int(100 * (frame + 1) * BLOCK /
                                                    (self.duration * SAMPLE_RATE))))
            if self.cancelled.is_set():
                return
            audio = np.concatenate(samples).astype(np.float32)
            if len(audio) < 3 * SAMPLE_RATE:
                raise ValueError("Voice profile must contain at least 3 seconds.")
            if level_db(audio) < -48:
                raise ValueError("Voice sample is too quiet. Move closer and try again.")
            path = profile_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(path), audio, SAMPLE_RATE, subtype="PCM_16")
            self.progress.emit(100)
            self.success.emit(str(path))
        except Exception as exc:
            if not self.cancelled.is_set():
                self.failure.emit(str(exc))
        finally:
            if self.session:
                self.session.close()
                self.session = None


class IsolationWorker(QThread):
    ready = Signal(str)
    levels = Signal(float, float)
    performance = Signal(str)
    error = Signal(str)
    stopped = Signal()
    preview_saved = Signal(str, str)

    def __init__(self, microphone: str, output: str | None,
                 voice_sample: str | None, parent=None):
        super().__init__(parent)
        self.microphone = microphone
        self.output = output
        self.voice_sample = voice_sample
        self.cancelled = threading.Event()
        self.session = None
        self.fifo = AudioFIFO(max_samples=SAMPLE_RATE // 2)
        self._writer = None
        self._writer_error = None
        self._preview_request = threading.Event()

    def stop(self):
        self.cancelled.set()
        if self.session:
            self.session.abort_capture()

    def request_preview(self):
        self._preview_request.set()

    def _output_loop(self):
        deadline = time.monotonic() + 0.06
        try:
            while not self.cancelled.is_set():
                remaining = deadline - time.monotonic()
                if remaining > 0 and self.cancelled.wait(remaining):
                    return
                self.session.write(self.fifo.pop(BLOCK))
                deadline = max(deadline + 0.04, time.monotonic())
        except Exception as exc:
            if not self.cancelled.is_set():
                self._writer_error = str(exc)
                self.cancelled.set()
                self.session.abort_capture()

    def run(self):
        preview_raw: list[np.ndarray] = []
        preview_clean: list[np.ndarray] = []
        preview_left = 0
        try:
            # Slow model initialization and possible download stay off the GUI thread.
            import voxlock

            model = voxlock.VoxLock(precision="int8", threads=1)
            if self.cancelled.is_set():
                return
            if self.voice_sample:
                sample = voxlock.load_audio(self.voice_sample)
                if len(sample) < SAMPLE_RATE * 3:
                    raise ValueError("Record at least 3 seconds of voice.")
                stream = model.stream(sample)
            else:
                stream = model.live()  # May pass through other voices while enrolling.
            self.session = make_session(self.microphone, self.output)
            self.session.open()
            if self.cancelled.is_set():
                return
            self._writer = threading.Thread(
                target=self._output_loop, name="voxlock-playback", daemon=True
            )
            self._writer.start()
            self.ready.emit("VoxLock Microphone" if platform.system() == "Linux"
                            else "VB-CABLE: choose CABLE Output as microphone")
            frames = 0
            start = time.monotonic()
            while not self.cancelled.is_set():
                pcm = self.session.read()
                t0 = time.monotonic()
                filtered = np.asarray(stream.push(pcm), dtype=np.float32)
                inference_ms = (time.monotonic() - t0) * 1000
                self.fifo.push(filtered)

                if self._preview_request.is_set():
                    self._preview_request.clear()
                    preview_left = int(5 * SAMPLE_RATE / BLOCK)
                    preview_raw, preview_clean = [], []
                if preview_left:
                    preview_raw.append(pcm.copy())
                    preview_clean.append(filtered.copy())
                    preview_left -= 1
                    if preview_left == 0:
                        self._save_preview(preview_raw, preview_clean)
                        preview_raw, preview_clean = [], []

                frames += 1
                if frames % 3 == 0:
                    self.levels.emit(level_db(pcm), level_db(filtered))
                if frames % 25 == 0:
                    self.performance.emit(
                        f"Inference: {inference_ms:.0f} ms / block · "
                        f"Buffered: {int(self.fifo.size * 1000 / SAMPLE_RATE)} ms"
                    )
                if self._writer_error:
                    raise RuntimeError(self._writer_error)
        except Exception as exc:
            if not self.cancelled.is_set() or self._writer_error:
                self.error.emit(str(exc))
        finally:
            self.cancelled.set()
            if self.session:
                self.session.abort_capture()
            if self._writer:
                self._writer.join(timeout=2)
            if self.session:
                self.session.close()
                self.session = None
            self.stopped.emit()

    def _save_preview(self, raw: list[np.ndarray], clean: list[np.ndarray]):
        directory = data_directory() / "previews"
        directory.mkdir(parents=True, exist_ok=True)
        source = np.concatenate(raw) if raw else np.empty(0, np.float32)
        target = np.concatenate(clean) if clean else np.empty(0, np.float32)
        # Model is delayed ~24ms: retain the actual result, do not fake alignment.
        raw_path = directory / "before.wav"
        clean_path = directory / "after.wav"
        sf.write(str(raw_path), source, SAMPLE_RATE, subtype="PCM_16")
        sf.write(str(clean_path), target, SAMPLE_RATE, subtype="PCM_16")
        self.preview_saved.emit(str(raw_path), str(clean_path))
