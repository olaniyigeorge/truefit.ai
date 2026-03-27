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
import time 
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
SILENCE_CHUNK = b"\x00\x00" * 160  # 10ms silence at 16kHz mono s16
_WEBRTC_SAMPLE_RATE = 48_000   # WebRTC/Opus expects this
_CHUNK_SAMPLES = int(_SAMPLE_RATE * _CHUNK_DURATION)   # 320
SILENCE_CHUNK = b"\x00\x00" * _CHUNK_SAMPLES       # 640 bytes — matches real frames



class AudioBridge:
    """
    Owns two queues:
      inbound_queue  — raw PCM bytes from the browser (agent consumes)
      outbound_queue — raw PCM bytes from the agent (sent to browser)
    """

    def __init__(self, *, context: SessionContext) -> None:
        self._ctx = context
        self.inbound_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=100)
        self.outbound_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=500)
        self._inbound_task: Optional[asyncio.Task] = None
        self._outbound_track: Optional[_AgentAudioTrack] = None
        self._closed = False
        self._track_attached = asyncio.Event() 
        self._agent_speaking = False


    def set_agent_speaking(self, speaking: bool) -> None:
        self._agent_speaking = speaking

    # ── Inbound (browser → agent) ─────────────────────────────────────────────

    async def attach_inbound_track(self, track: MediaStreamTrack) -> None:
        """Start pumping audio from the WebRTC track into inbound_queue."""
        logger.info(f"[{self._ctx.session_id}] Attaching inbound audio track")
        self._inbound_task = asyncio.create_task(
            self._pump_inbound(track),
            name=f"audio-inbound-{self._ctx.session_id}",
        )
        self._track_attached.set() 

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
        await asyncio.wait_for(self._track_attached.wait(), timeout=30.0)
        chunk_count = 0
        while True:
            try:
                chunk = await asyncio.wait_for(self.inbound_queue.get(), timeout=2.0)
                if chunk is None:
                    return  # bridge closed
                chunk_count += 1
                if chunk_count % 100 == 0:
                    logger.info(f"[{self._ctx.session_id}] Sent {chunk_count} chunks to Gemini")
                yield chunk
            except asyncio.TimeoutError:
                continue
                
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

    async def clear_outbound_queue(self) -> None:
        """Drain the outbound queue and clear the resampler buffer — called on interrupt or turn complete."""
        while not self.outbound_queue.empty():
            try:
                self.outbound_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # Also clear the resampler's internal buffer so stale PCM doesn't replay
        if self._outbound_track is not None:
            self._outbound_track.clear_buf()


    async def push_audio(self, pcm_bytes: bytes) -> None:
        """
        Called by the agent to push a PCM response chunk toward the browser.
        Non-blocking — drops if queue is full (prefer freshness over latency).
        """
        self._agent_speaking = True
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
    Pulls 24kHz PCM from the agent queue, resamples to 48kHz,
    and outputs exactly one 20ms frame per recv() call — paced correctly.
    """

    def __init__(self, *, queue: asyncio.Queue, session_id: str) -> None:
        super().__init__()
        self._queue = queue
        self._session_id = session_id
        self._sample_rate = _WEBRTC_SAMPLE_RATE          # 48000
        self._samples_per_frame = int(_WEBRTC_SAMPLE_RATE * _CHUNK_DURATION)  # 960
        self._resampler = av.AudioResampler(
            format="s16", layout="mono", rate=_WEBRTC_SAMPLE_RATE
        )
        self._buf = bytearray()   # ring buffer of resampled 48kHz s16 PCM
        self._pts = 0
        self._start: Optional[float] = None

    def clear_buf(self) -> None:
        """Discard any buffered PCM — called when the agent turn is interrupted or complete."""
        self._buf.clear()

    async def recv(self) -> av.AudioFrame:
        # ── Pace to exactly 20ms intervals (mirrors aiortc base class) ──
        if self._start is None:
            self._start = time.time()
        else:
            self._pts += self._samples_per_frame
            deadline = self._start + (self._pts / self._sample_rate)
            wait = deadline - time.time()
            if wait > 0:
                await asyncio.sleep(wait)

        # ── Drain queue into buffer until we have a full frame ──
        target = self._samples_per_frame * 2   # bytes needed (s16 = 2 bytes/sample)

        while len(self._buf) < target:
            try:
                pcm_24k = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break   # pad with silence below

            if pcm_24k is None:
                raise Exception("AudioBridge closed")

            # Resample 24kHz → 48kHz
            n = len(pcm_24k) // 2
            in_frame = av.AudioFrame(format="s16", layout="mono", samples=n)
            in_frame.planes[0].update(pcm_24k)
            in_frame.sample_rate = _OUTPUT_SAMPLE_RATE
            in_frame.time_base = fractions.Fraction(1, _OUTPUT_SAMPLE_RATE)
            in_frame.pts = 0
            for rf in self._resampler.resample(in_frame):
                self._buf.extend(bytes(rf.planes[0]))

        # ── Slice exactly one frame, pad with silence if needed ──
        if len(self._buf) >= target:
            out_pcm = bytes(self._buf[:target])
            del self._buf[:target]
        else:
            silence_needed = target - len(self._buf)
            out_pcm = bytes(self._buf) + b"\x00\x00" * (silence_needed // 2)
            self._buf.clear()

        frame = av.AudioFrame(format="s16", layout="mono", samples=self._samples_per_frame)
        frame.planes[0].update(out_pcm)
        frame.sample_rate = self._sample_rate
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        frame.pts = self._pts
        return frame