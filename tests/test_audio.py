"""Unit tests; no microphone, PipeWire or VoxLock model needed."""
import numpy as np

from voxlock_desktop.devices import SAMPLE_RATE, BLOCK, _read_exact
from voxlock_desktop.engine import AudioFIFO, data_directory, level_db


def test_constant_rate():
    assert SAMPLE_RATE == 16000
    assert BLOCK == 640


def test_levels():
    assert level_db(np.zeros(640, dtype=np.float32)) == -80.0
    assert abs(level_db(np.ones(640, dtype=np.float32))) < 0.01
    assert abs(level_db(np.full(640, 0.1, dtype=np.float32)) + 20.0) < 0.1


def test_fifo_order_and_silence():
    queue = AudioFIFO(max_samples=12)
    queue.push(np.array([1, 2, 3, 4, 5], dtype=np.float32))
    assert queue.pop(3).tolist() == [1, 2, 3]
    queue.push(np.array([6, 7], dtype=np.float32))
    assert queue.pop(5).tolist() == [4, 5, 6, 7, 0]


def test_fifo_overflow_drops_oldest_block():
    queue = AudioFIFO(max_samples=4)
    queue.push(np.array([1, 2, 3], dtype=np.float32))
    queue.push(np.array([4, 5, 6], dtype=np.float32))
    assert queue.dropped == 3
    assert queue.pop(4).tolist() == [4, 5, 6, 0]


def test_profile_location_is_user_private():
    assert data_directory().is_absolute()


def test_pulse_frame_reader_handles_short_reads():
    class Stream:
        def __init__(self):
            self.parts = iter((b"ab", b"c", b"def"))
        def read(self, n):
            return next(self.parts, b"")
    assert _read_exact(Stream(), 6) == b"abcdef"
