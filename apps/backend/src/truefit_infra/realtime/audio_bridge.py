# /truefit_infra/realtime/audio_bridge.py
"""
AudioBridge — bidirectional audio pipe between WebRTC and the agent.

Inbound:  WebRTC audio track  →  asyncio.Queue[bytes]  (agent reads this)
Outbound: asyncio.Queue[bytes] (agent writes this)  →  WebRTC audio track

No blocking calls. No domain logic.
"""
from __future__ import annotations

import asyncio
import fractions
from typing import AsyncIterator, Optional

import av
from aiortc import MediaStreamTrack
from aiortc.mediastreams import AudioStreamTrack

from src.truefit_infra.realtime.session_context import SessionContext
from src.truefit_core.common.utils import logger

# PCM format expected by Gemini Live API
_SAMPLE_RATE = 16_000   # 16 kHz
_CHANNELS = 1           # mono
_SAMPLE_WIDTH = 2       # 16-bit (s16)
_CHUNK_DURATION = 0.02  # 20ms chunks → 320 samples per chunk


class AudioBridge:
    """
    Owns two queues:
      inbound_queue  — raw PCM bytes from the browser (agent consumes)
      outbound_queue — raw PCM bytes from the agent (sent to browser)
    """

    def __init__(self, *, context: SessionContext) -> None:
        self._ctx = context
        self.inbound_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=100)
        self.outbound_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=100)

        self._inbound_task: Optional[asyncio.Task] = None
        self._outbound_track: Optional[_AgentAudioTrack] = None
        self._closed = False

    # ── Inbound (browser → agent) ─────────────────────────────────────────────

    async def attach_inbound_track(self, track: MediaStreamTrack) -> None:
        """Start pumping audio from the WebRTC track into inbound_queue."""
        self._inbound_task = asyncio.create_task(
            self._pump_inbound(track),
            name=f"audio-inbound-{self._ctx.session_id}",
        )

    async def _pump_inbound(self, track: MediaStreamTrack) -> None:
        """
        Tight async loop: pull frames from aiortc, resample to 16kHz mono s16,
        chunk into 20ms pieces, enqueue raw bytes.
        """
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=_SAMPLE_RATE,
        )
        try:
            while not self._closed:
                try:
                    frame: av.AudioFrame = await asyncio.wait_for(
                        track.recv(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.warning(f"[{self._ctx.session_id}] Inbound track error: {e}")
                    break

                # Resample to target format
                resampled_frames = resampler.resample(frame)
                for rf in resampled_frames:
                    pcm_bytes: bytes = bytes(rf.planes[0])
                    # Chunk into fixed 20ms pieces
                    chunk_size = int(_SAMPLE_RATE * _CHUNK_DURATION) * _SAMPLE_WIDTH
                    for i in range(0, len(pcm_bytes), chunk_size):
                        chunk = pcm_bytes[i : i + chunk_size]
                        if len(chunk) == chunk_size:
                            try:
                                self.inbound_queue.put_nowait(chunk)
                            except asyncio.QueueFull:
                                # Drop oldest chunk to avoid growing unbounded
                                try:
                                    self.inbound_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                                self.inbound_queue.put_nowait(chunk)

        except asyncio.CancelledError:
            pass
        finally:
            await self.inbound_queue.put(None)  # sentinel → agent sees end of stream

    # ── Agent-facing async generator ─────────────────────────────────────────

    async def audio_input_stream(self) -> AsyncIterator[bytes]:
        """
        Async generator the agent iterates to receive PCM audio.
        Mirrors the interface your existing InterviewConnection uses.
        """
        while True:
            chunk = await self.inbound_queue.get()
            if chunk is None:
                break
            yield chunk

    # ── Outbound (agent → browser) ────────────────────────────────────────────

    def create_outbound_track(self) -> "_AgentAudioTrack":
        """
        Returns an aiortc-compatible track the agent pushes PCM into.
        Pass this track to WebRTCClient.add_outbound_audio_track().
        """
        self._outbound_track = _AgentAudioTrack(
            queue=self.outbound_queue,
            session_id=self._ctx.session_id,
        )
        return self._outbound_track

    async def push_audio(self, pcm_bytes: bytes) -> None:
        """
        Called by the agent to push a PCM response chunk toward the browser.
        Non-blocking — drops if queue is full (prefer freshness over latency).
        """
        try:
            self.outbound_queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            logger.debug(f"[{self._ctx.session_id}] Outbound audio queue full, dropping chunk")

    # ── Teardown ──────────────────────────────────────────────────────────────

    async def close(self) -> None:
        self._closed = True
        if self._inbound_task:
            self._inbound_task.cancel()
            try:
                await self._inbound_task
            except asyncio.CancelledError:
                pass
        await self.inbound_queue.put(None)
        await self.outbound_queue.put(None)


# ── Outbound aiortc track ─────────────────────────────────────────────────────

class _AgentAudioTrack(AudioStreamTrack):
    """
    aiortc AudioStreamTrack that pulls from the agent's outbound queue.
    aiortc calls recv() on a timer; we block until a chunk is available.
    """

    def __init__(self, *, queue: asyncio.Queue[Optional[bytes]], session_id: str) -> None:
        super().__init__()
        self._queue = queue
        self._session_id = session_id
        self._timestamp = 0
        self._sample_rate = _SAMPLE_RATE
        self._samples_per_frame = int(_SAMPLE_RATE * _CHUNK_DURATION)

    async def recv(self) -> av.AudioFrame:
        # Wait for agent to produce audio
        pcm_bytes = await self._queue.get()
        if pcm_bytes is None:
            raise Exception("AudioBridge closed")  # aiortc will stop calling recv()

        frame = av.AudioFrame(format="s16", layout="mono", samples=self._samples_per_frame)
        frame.planes[0].update(pcm_bytes)
        frame.sample_rate = self._sample_rate
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        frame.pts = self._timestamp
        self._timestamp += self._samples_per_frame
        return frame