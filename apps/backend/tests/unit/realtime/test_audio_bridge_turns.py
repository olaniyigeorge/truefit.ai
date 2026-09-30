import asyncio
import math
import random
import uuid
from array import array

import av
import pytest

from src.truefit_infra.realtime.audio_bridge import AudioBridge
from src.truefit_infra.realtime.session_context import SessionContext

pytestmark = pytest.mark.unit

RATE = 48_000
FRAME = 960  # 20ms at 48kHz


def _ctx() -> SessionContext:
    return SessionContext(session_id="s1", job_id=uuid.uuid4(), candidate_id=uuid.uuid4())


def _frame(rms: float, rng: random.Random) -> av.AudioFrame:
    peak = rms * math.sqrt(3)
    samples = array("h", (int(rng.uniform(-peak, peak)) for _ in range(FRAME)))
    f = av.AudioFrame(format="s16", layout="mono", samples=FRAME)
    f.planes[0].update(samples.tobytes())
    f.sample_rate = RATE
    return f


class _Track:
    """Yields the scripted frames, then stalls like a quiet network track."""

    def __init__(self, frames):
        self._frames = iter(frames)
        self.exhausted = asyncio.Event()

    async def recv(self):
        try:
            return next(self._frames)
        except StopIteration:
            self.exhausted.set()
            await asyncio.sleep(3600)


def _speech(seconds, rng):
    return [
        _frame(3000 * (0.2 + 0.8 * abs(math.sin(2 * math.pi * 4 * i * 0.02))), rng)
        for i in range(int(seconds / 0.02))
    ]


async def _run(frames):
    bridge = AudioBridge(context=_ctx())
    events = []

    async def start():
        events.append("start")

    async def end():
        events.append("end")

    bridge._on_activity_start = start
    bridge._on_activity_end = end
    bridge.open_mic()
    bridge._last_activity_start = -10  # the debounce is relative to the monotonic clock
    track = _Track(frames)
    task = asyncio.create_task(bridge._pump_inbound(track))
    await asyncio.wait_for(track.exhausted.wait(), timeout=30)
    await asyncio.sleep(0.05)  # let the scheduled callbacks run
    bridge._closed = True
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return bridge, events


async def test_steady_fan_noise_does_not_start_a_turn():
    rng = random.Random(1)
    _, events = await _run([_frame(900, rng) for _ in range(300)])
    assert events == []


async def test_speech_after_quiet_starts_a_turn_and_locks_until_the_agent_responds():
    rng = random.Random(2)
    frames = [_frame(30, rng) for _ in range(50)] + _speech(1.5, rng) + [_frame(30, rng) for _ in range(80)]
    bridge, events = await _run(frames)
    assert events == ["start", "end"]
    assert bridge._vad_waiting_for_response

    bridge.on_agent_responded()
    assert not bridge._vad_waiting_for_response
    assert not bridge._turn_detector.is_speaking
