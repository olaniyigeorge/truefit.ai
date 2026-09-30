"""
Streaming mono s16 PCM resampler for adapters whose provider wants a different
rate than the audio path delivers (for example OpenAI GA needs 24kHz input while
the bridge supplies 16kHz).

Stateful across chunks so no clicks appear at chunk boundaries. Not thread-safe:
use one instance per session.
"""

from __future__ import annotations

import fractions

import av


class PcmResampler:
    def __init__(self, in_rate: int, out_rate: int) -> None:
        self._in_rate = in_rate
        self._out_rate = out_rate
        self._carry = b""  # a trailing odd byte from the previous chunk
        self._resampler: av.AudioResampler | None = None
        self._pts = 0
        self.reset()

    @property
    def is_passthrough(self) -> bool:
        return self._in_rate == self._out_rate

    def reset(self) -> None:
        """Forget all history. Call when a new session starts."""
        self._carry = b""
        self._pts = 0
        self._resampler = (
            None
            if self.is_passthrough
            else av.AudioResampler(format="s16", layout="mono", rate=self._out_rate)
        )

    def process(self, pcm: bytes) -> bytes:
        """Resample one chunk. May return fewer bytes than the ratio implies while
        the resampler primes, but never drops audio over the length of a stream."""
        if self.is_passthrough:
            return pcm
        data = self._carry + pcm
        usable = len(data) - (len(data) % 2)  # whole 16-bit samples only
        self._carry = data[usable:]
        if usable == 0:
            return b""
        samples = usable // 2
        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(data[:usable])
        frame.sample_rate = self._in_rate
        frame.time_base = fractions.Fraction(1, self._in_rate)
        frame.pts = self._pts
        self._pts += samples
        # Frame planes are padded, so trim to the real sample count.
        return b"".join(
            bytes(out.planes[0])[: out.samples * 2]
            for out in self._resampler.resample(frame)
        )
