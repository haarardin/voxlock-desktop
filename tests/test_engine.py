"""Exercise processing lifecycle without a physical microphone or model download."""
import sys
import time
from types import SimpleNamespace

import numpy as np

from voxlock_desktop import engine


def test_enrolled_stream_outputs_only_model_audio_and_cleans_up(monkeypatch):
    instances = []

    class FakeSession:
        def __init__(self):
            self.opens = 0
            self.closes = 0
            self.read_count = 0
            self.outputs = []
            instances.append(self)

        def open(self):
            self.opens += 1

        def read(self):
            self.read_count += 1
            time.sleep(0.04)
            if self.read_count > 8:
                raise RuntimeError("simulated microphone disconnect")
            return np.ones(engine.BLOCK, dtype=np.float32)

        def write(self, audio):
            self.outputs.append(audio.copy())

        def abort_capture(self):
            pass

        def close(self):
            self.closes += 1

    class FakeStream:
        def push(self, block):
            # Model explicitly mutes a speaker; raw audio must never be output.
            return np.zeros_like(block)

    class FakeModel:
        def __init__(self, precision, threads):
            assert precision == "int8"
            assert threads == 1

        def stream(self, sample):
            assert len(sample) >= engine.SAMPLE_RATE * 3
            return FakeStream()

    fake_voxlock = SimpleNamespace(
        VoxLock=FakeModel,
        load_audio=lambda path: np.zeros(engine.SAMPLE_RATE * 3, np.float32),
    )
    monkeypatch.setitem(sys.modules, "voxlock", fake_voxlock)
    monkeypatch.setattr(engine, "make_session",
                        lambda microphone, output: FakeSession())

    worker = engine.IsolationWorker("test_microphone", None, "sample.wav")
    errors = []
    worker.error.connect(errors.append)
    # Execute synchronously; only the playback sub-thread runs concurrently.
    worker.run()
    assert len(instances) == 1
    assert instances[0].opens == 1
    assert instances[0].closes == 1
    assert instances[0].read_count == 9
    assert instances[0].outputs, "playback writer did not run"
    assert all(np.all(x == 0) for x in instances[0].outputs)
    assert worker.cancelled.is_set()
