import math
import struct

import pytest

from src.truefit_infra.llm.pcm_resampler import PcmResampler

pytestmark = pytest.mark.unit


def _tone(n: int, rate: int = 16_000, start: int = 0) -> bytes:
    return struct.pack(
        f"<{n}h", *[int(8000 * math.sin(2 * math.pi * 440 * (start + i) / rate)) for i in range(n)]
    )


def _stream(chunks: int, chunk_samples: int = 320) -> bytes:
    r = PcmResampler(16_000, 24_000)
    return b"".join(r.process(_tone(chunk_samples, start=i * chunk_samples)) for i in range(chunks))


def test_upsamples_16k_to_24k_at_the_right_ratio():
    out = _stream(50)  # 1 second in
    assert len(out) % 2 == 0
    assert abs(len(out) // 2 - 24_000) < 100  # within a few ms of exactly 1.5x


def test_steady_state_chunk_size_is_exact():
    r = PcmResampler(16_000, 24_000)
    sizes = [len(r.process(_tone(320, start=i * 320))) for i in range(10)]
    assert sizes[-1] == 960 and sizes[-2] == 960  # 20ms in -> 480 samples -> 960 bytes


def test_output_is_not_padded_beyond_the_real_samples():
    """Regression guard: av frame planes are padded, output must be trimmed."""
    r = PcmResampler(16_000, 24_000)
    for i in range(20):
        assert len(r.process(_tone(320, start=i * 320))) % 2 == 0
    assert len(_stream(50)) < 24_000 * 2 + 400  # padding would blow well past this


def test_output_keeps_the_signal_not_silence():
    out = _stream(10)
    samples = struct.unpack(f"<{len(out) // 2}h", out)
    assert max(abs(s) for s in samples) > 5000


def test_odd_byte_chunks_lose_no_audio():
    whole = PcmResampler(16_000, 24_000)
    split = PcmResampler(16_000, 24_000)
    data = _tone(3200)
    a = whole.process(data)
    b = split.process(data[:1001]) + split.process(data[1001:])
    assert len(a) == len(b)


def test_empty_and_single_byte_chunks_are_safe():
    r = PcmResampler(16_000, 24_000)
    assert r.process(b"") == b""
    assert r.process(b"\x01") == b""


def test_same_rate_is_passthrough():
    r = PcmResampler(24_000, 24_000)
    data = _tone(320, 24_000)
    assert r.is_passthrough and r.process(data) == data


def test_reset_clears_state():
    r = PcmResampler(16_000, 24_000)
    r.process(b"\x01")
    r.reset()
    first = len(r.process(_tone(320)))
    fresh = len(PcmResampler(16_000, 24_000).process(_tone(320)))
    assert first == fresh
