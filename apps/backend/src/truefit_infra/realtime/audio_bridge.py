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
_OUTPUT_SAMPLE_RATE = 24_000   # Gemini outputs this
_OUTPUT_CHUNK_DURATION = 0.02
SILENCE_CHUNK = b"\x00\x00" * 160  # 10ms silence at 16kHz mono s16
_WEBRTC_SAMPLE_RATE = 48_000   # WebRTC/Opus expects this


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
        logger.info(f"[{self._ctx.session_id}] Attaching inbound audio track")
        self._inbound_task = asyncio.create_task(
            self._pump_inbound(track),
            name=f"audio-inbound-{self._ctx.session_id}",
        )

    async def _pump_inbound(self, track: MediaStreamTrack) -> None:
        """
        Tight async loop: pull frames from aiortc, resample to 16kHz mono s16,
        chunk into 20ms pieces, enqueue raw bytes.
        """
        logger.info(f"\n\n[{self._ctx.session_id}] _pump_inbound started\n") 
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=_SAMPLE_RATE,
        )
        frame_count = 0 
        try:
            while not self._closed:
                try:
                    frame: av.AudioFrame = await asyncio.wait_for(
                        track.recv(), timeout=1.0
                    )
                    frame_count += 1
                    if frame_count % 50 == 0:  # ← log every ~1s
                        logger.info(f"\n[{self._ctx.session_id}] Inbound frames: {frame_count}\n")
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
        chunk_count = 0
        while True:
            try:
                chunk = await asyncio.wait_for(self.inbound_queue.get(), timeout=0.5)
                if chunk is None:
                    return
                chunk_count += 1
                if chunk_count % 50 == 0:
                    logger.info(f"\n[{self._ctx.session_id}] Sent {chunk_count} chunks to Gemini\n")
                yield chunk
            except asyncio.TimeoutError:
                yield SILENCE_CHUNK

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

class _AgentAudioTrack(AudioStreamTrack):
    """
    aiortc AudioStreamTrack that pulls from the agent's outbound queue.
    aiortc calls recv() on a timer; we block until a chunk is available.
    """

    def __init__(self, *, queue, session_id):
        super().__init__()
        self._queue = queue
        self._session_id = session_id
        self._timestamp = 0
        self._sample_rate = _WEBRTC_SAMPLE_RATE
        self._samples_per_frame = int(_WEBRTC_SAMPLE_RATE * _CHUNK_DURATION)  # 960
        self._resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=_WEBRTC_SAMPLE_RATE,
        )

    async def recv(self) -> av.AudioFrame:
        try:
            pcm_bytes = await asyncio.wait_for(self._queue.get(), timeout=0.02)
            if pcm_bytes is None:
                raise Exception("AudioBridge closed")
        except asyncio.TimeoutError:
            pcm_bytes = b"\x00\x00" * (int(_OUTPUT_SAMPLE_RATE * _CHUNK_DURATION) * 2)

        samples_in = len(pcm_bytes) // 2
        in_frame = av.AudioFrame(format="s16", layout="mono", samples=samples_in)
        in_frame.planes[0].update(pcm_bytes)
        in_frame.sample_rate = _OUTPUT_SAMPLE_RATE
        in_frame.time_base = fractions.Fraction(1, _OUTPUT_SAMPLE_RATE)
        in_frame.pts = 0  # resampler doesn't need pts

        resampled = self._resampler.resample(in_frame)
        if not resampled:
            samples_out = self._samples_per_frame
            out_pcm = b"\x00\x00" * samples_out
        else:
            rf = resampled[0]
            out_pcm = bytes(rf.planes[0])
            samples_out = len(out_pcm) // 2  # ← derive from actual bytes, not rf.samples

        frame = av.AudioFrame(format="s16", layout="mono", samples=samples_out)
        frame.planes[0].update(out_pcm)
        frame.sample_rate = _WEBRTC_SAMPLE_RATE
        frame.time_base = fractions.Fraction(1, _WEBRTC_SAMPLE_RATE)
        frame.pts = self._timestamp
        self._timestamp += samples_out
        return frame