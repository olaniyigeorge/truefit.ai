"""
AudioBridge - bidirectional audio pipe between WebRTC and the agent.

─────────────────────
WHAT THIS MODULE DOES
─────────────────────
This is the audio plumbing layer. It sits between two worlds:

  LEFT SIDE:  WebRTC peer connection (aiortc)
                -> delivers browser audio as av.AudioFrame objects (48kHz Opus decoded)
                ← expects av.AudioFrame objects to send to the browser (48kHz)

  RIGHT SIDE: The interview agent (GeminiLiveAdapter)
                -> expects 16kHz mono s16 PCM bytes (Gemini's input format)
                ← produces 24kHz mono s16 PCM bytes (Gemini's output format)

AudioBridge bridges these two worlds by:
  INBOUND:  WebRTC frame -> resample 48kHz -> 16kHz -> chunk into 20ms pieces -> asyncio Queue
  OUTBOUND: asyncio Queue of 24kHz PCM -> resample 24kHz -> 48kHz -> av.AudioFrame -> WebRTC

No domain logic lives here. No Gemini calls. No WebSocket writes.
This module only moves audio bytes between queues and tracks.

KEY DESIGN DECISIONS

1. MIC GATING: The mic starts CLOSED. It only opens after the agent's first
   turn completes (called from InterviewConnection._on_turn_complete). This
   prevents the candidate's audio from reaching Gemini before it's ready to
   listen. open_mic() / close_mic() control this gate.

2. ECHO SUPPRESSION: A cooldown timer (_speaking_cooldown_until) suppresses
   inbound audio for 600ms after the agent stops speaking. This prevents the
   agent's own voice (coming back through the WebRTC echo path) from being
   sent to Gemini as candidate speech.

3. NON-BLOCKING QUEUES: Both queues use put_nowait(). If full, inbound drops
   the oldest chunk (LRU - freshness matters more than completeness). Outbound
   logs and drops (we'd rather miss a frame than block the event loop).

4. PACED OUTPUT: _AgentAudioTrack.recv() paces itself to exactly 20ms intervals
   using a pts-based clock. This matches what WebRTC expects and prevents
   jitter-caused audio glitches in the browser.
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

# ──────────────────────
# AUDIO FORMAT CONSTANTS
# ──────────────────────
_SAMPLE_RATE = 16_000  # Gemini expects 16kHz inbound
_CHANNELS = 1  # mono - both Gemini and the bridge use mono
_SAMPLE_WIDTH = 2  # 16-bit PCM = 2 bytes per sample (s16)
_CHUNK_DURATION = 0.02  # 20ms chunks - standard WebRTC frame size
_OUTPUT_SAMPLE_RATE = 24_000  # Gemini outputs at 24kHz
SILENCE_CHUNK = b"\x00\x00" * 160  # (overwritten below - see note)
_WEBRTC_SAMPLE_RATE = 48_000  # aiortc/Opus expects 48kHz
_CHUNK_SAMPLES = int(
    _SAMPLE_RATE * _CHUNK_DURATION
)  # 320 samples per 20ms chunk at 16kHz
# Final SILENCE_CHUNK: 320 samples × 2 bytes = 640 bytes of silence at 16kHz mono s16
# This matches the exact size of a real 20ms inbound chunk so queues stay consistent.
SILENCE_CHUNK = b"\x00\x00" * _CHUNK_SAMPLES


class AudioBridge:
    """
    The central audio routing object for one interview session.

    Created by WebRTCSignaling (or WebRTCClient) when the peer connection is
    established. Passed to the agent via InterviewConnection._audio_input_stream()
    and _on_audio_output().

    One AudioBridge per session - it holds:
      inbound_queue:  raw 16kHz PCM bytes flowing FROM the browser TO Gemini
      outbound_queue: raw 24kHz PCM bytes flowing FROM Gemini TO the browser
    """

    def __init__(self, *, context: SessionContext) -> None:
        self._ctx = context
        # inbound_queue: browser mic audio -> agent -> Gemini
        # maxsize=100 -> about 2 seconds of audio buffering at 20ms chunks
        self.inbound_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=100)
        # outbound_queue: Gemini response audio -> WebRTC track -> browser speaker
        # maxsize=500 -> about 10 seconds of response buffering (generous for latency spikes)
        self.outbound_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=500)
        self._inbound_task: Optional[asyncio.Task] = None  # The _pump_inbound task
        self._outbound_track: Optional[_AgentAudioTrack] = (
            None  # Set by create_outbound_track()
        )
        self._closed = False
        self._track_attached = asyncio.Event()  # Set when inbound WebRTC track arrives
        self._agent_speaking = False  # True while agent is actively outputting audio
        self._speaking_cooldown_until: float = (
            0.0  # epoch time - suppress echo until this
        )
        self._mic_open = (
            asyncio.Event()
        )  # Gate: inbound audio only flows when this is set

    def open_mic(self) -> None:
        """
        Opens the microphone gate - inbound audio from the browser starts
        flowing into inbound_queue and onward to Gemini.

        Called by InterviewConnection._on_turn_complete() after the agent
        finishes its first (and each subsequent) response turn.

        Must NOT be called before the agent has finished its opening greeting -
        doing so would send the candidate's audio to Gemini before it's in
        listening mode, causing confusion.
        """
        self._mic_open.set()

    def close_mic(self) -> None:
        """
        Closes the microphone gate - inbound audio from the browser is
        discarded in _pump_inbound without being queued.

        Called:
          - At connection start (explicitly in InterviewConnection.run()) - keeps
            mic closed until the agent is ready to listen.
          - At the start of _on_turn_complete() - prevents candidate audio from
            reaching Gemini during the turn transition / resampler reset window.
        """
        self._mic_open.clear()

    def set_agent_speaking(self, speaking: bool) -> None:
        """
        Marks whether the agent is currently producing audio output.

        When speaking=False, starts a 600ms echo suppression cooldown.
        During this window, inbound audio from the browser is discarded
        even if the mic is open - this absorbs the echo/tail of the agent's
        own voice that comes back through the WebRTC path.

        600ms is a tuning parameter. Too short -> agent hears its own voice.
        Too long -> candidate's first word(s) get dropped.
        """
        self._agent_speaking = speaking
        if not speaking:
            # 600ms cooldown after agent stops - absorbs echo/tail audio
            self._speaking_cooldown_until = time.monotonic() + 0.6

    # ─────────────────────────
    # INBOUND: BROWSER -> AGENT
    # ─────────────────────────

    async def attach_inbound_track(self, track: MediaStreamTrack) -> None:
        """
        Called by WebRTCClient when the browser's audio track arrives via
        the peer connection. Starts the background pump task that continuously
        pulls frames from the track and feeds them into inbound_queue.

        Also sets _track_attached so audio_input_stream() (which waits on it)
        can proceed.
        """
        logger.info(f"[{self._ctx.session_id}] Attaching inbound audio track")
        self._inbound_task = asyncio.create_task(
            self._pump_inbound(track),
            name=f"audio-inbound-{self._ctx.session_id}",
        )
        self._track_attached.set()

    async def _pump_inbound(self, track: MediaStreamTrack) -> None:
        """
        The core inbound pipeline - runs as a background task for the entire
        session. Continuously pulls av.AudioFrame objects from the WebRTC track,
        resamples them from 48kHz to 16kHz mono s16 PCM, chunks into 20ms pieces,
        and puts them in inbound_queue for the agent to consume.

        GATING: Frames are discarded entirely if the mic is closed. This is
        the primary mechanism for keeping candidate audio away from Gemini
        during agent turns.

        ECHO SUPPRESSION: After the agent stops speaking, a cooldown timer
        causes chunks to be dropped even when the mic is open. This prevents
        the agent's voice (echoing back through WebRTC) from reaching Gemini.

        QUEUE FULL HANDLING: If the queue is full (100 chunks ≈ 2s of audio),
        we drop the oldest chunk and enqueue the new one. Freshness > completeness.

        The task ends (and puts None in the queue as a sentinel) when:
          - self._closed is set (bridge teardown)
          - The track throws an unrecoverable error
          - The task is cancelled (CancelledError)
        """
        logger.info(f"\n\n[{self._ctx.session_id}] _pump_inbound started\n")
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=_SAMPLE_RATE,  # 16kHz target
        )
        frame_count = 0
        try:
            while not self._closed:
                try:
                    frame = await asyncio.wait_for(track.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    # No frame for 1s - normal during silences, just continue
                    continue
                except Exception as e:
                    logger.warning(f"[{self._ctx.session_id}] Inbound track error: {e}")
                    break

                # MIC GATE: discard frame if mic is closed (agent is speaking
                # or we're in the transition window)
                if not self._mic_open.is_set():
                    continue  # discard frame entirely, don't even resample

                resampled_frames = resampler.resample(frame)
                for rf in resampled_frames:
                    pcm_bytes = bytes(rf.planes[0])
                    chunk_size = (
                        int(_SAMPLE_RATE * _CHUNK_DURATION) * _SAMPLE_WIDTH
                    )  # 640 bytes
                    for i in range(0, len(pcm_bytes), chunk_size):
                        chunk = pcm_bytes[i : i + chunk_size]
                        if len(chunk) == chunk_size:  # Only enqueue full 20ms chunks
                            # ECHO SUPPRESSION: drop chunk during cooldown window
                            if time.monotonic() < self._speaking_cooldown_until:
                                continue
                            try:
                                self.inbound_queue.put_nowait(chunk)
                            except asyncio.QueueFull:
                                # Drop oldest to make room for newest
                                try:
                                    self.inbound_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                                self.inbound_queue.put_nowait(chunk)
        except asyncio.CancelledError:
            pass
        finally:
            # Sentinel: tells audio_input_stream() the bridge is done
            await self.inbound_queue.put(None)

    # ────────────────────────────
    # AGENT-FACING ASYNC GENERATOR
    # ────────────────────────────

    async def audio_input_stream(self) -> AsyncIterator[bytes]:
        """
        Async generator that the agent iterates to get microphone audio chunks.

        Used by LiveInterviewAgent._send_audio_loop() which passes it to
        GeminiLiveAdapter.send_audio() in a tight loop.

        Waits up to 30 seconds for the WebRTC inbound track to be attached
        before yielding any chunks (via _track_attached event). After that,
        it reads from inbound_queue indefinitely with 2s timeouts (to handle
        silent periods without blocking forever).

        Returns (generator ends) when a None sentinel is dequeued - this
        happens when _pump_inbound ends (bridge closed or track error).

        Yields: 640-byte chunks of 16kHz mono s16 PCM (20ms each)
        """
        await asyncio.wait_for(self._track_attached.wait(), timeout=30.0)
        chunk_count = 0
        while True:
            try:
                chunk = await asyncio.wait_for(self.inbound_queue.get(), timeout=2.0)
                if chunk is None:
                    return  # bridge closed - stop the generator
                chunk_count += 1
                if chunk_count % 100 == 0:
                    logger.info(
                        f"[{self._ctx.session_id}] Sent {chunk_count} chunks to Gemini"
                    )
                yield chunk
            except asyncio.TimeoutError:
                # Queue was empty for 2s - normal during agent turns when mic is closed
                continue

    # ──────────────────────────
    # OUTBOUND: AGENT -> BROWSER
    # ──────────────────────────

    def create_outbound_track(self) -> "_AgentAudioTrack":
        """
        Creates and returns the aiortc-compatible audio track that streams
        agent audio to the browser.

        Called during WebRTC setup. The returned track is added to the
        RTCPeerConnection's media stream so the browser receives it as
        a standard WebRTC audio track.

        The track pulls from outbound_queue, resamples 24kHz -> 48kHz, and
        delivers exactly one 20ms frame per recv() call - paced correctly
        so the browser's audio renderer plays it smoothly.
        """
        self._outbound_track = _AgentAudioTrack(
            queue=self.outbound_queue,
            session_id=self._ctx.session_id,
        )
        return self._outbound_track

    async def clear_outbound_queue(self) -> None:
        """
        Immediately discards all queued agent audio and resets the track's
        internal state (resampler, buffer, pts clock).

        Called in two situations:
          1. Interrupt: candidate started talking - stop playing immediately
          2. Turn complete: after all queued audio has drained - reset cleanly
             before the next turn to avoid resampler state contamination.

        The track's clear_buf() also reinstantiates the resampler to guarantee
        clean state (resampler internal buffers can hold partial frames).
        """
        while not self.outbound_queue.empty():
            try:
                self.outbound_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._outbound_track is not None:
            self._outbound_track.clear_buf()  # resets buffer, resampler, pts, and _start

    async def push_audio(self, pcm_bytes: bytes) -> None:
        """
        Called by InterviewConnection._on_audio_output() for each audio chunk
        received from Gemini. Puts the chunk in the outbound queue.

        The _AgentAudioTrack.recv() on the other end drains this queue,
        resamples to 48kHz, and delivers frames to the browser.

        Non-blocking: if the queue is full (500 chunks ≈ 10s), we log and
        drop the chunk. This is a safety valve - in normal operation the
        browser consumes frames fast enough that the queue stays shallow.
        """
        try:
            self.outbound_queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            logger.debug(
                f"[{self._ctx.session_id}] Outbound audio queue full, dropping chunk"
            )

    # ────────
    # TEARDOWN
    # ────────

    async def close(self) -> None:
        """
        Shuts down the AudioBridge. Called when the interview session ends.

        1. Sets _closed so _pump_inbound exits its while loop.
        2. Cancels the pump task to stop immediately if it's waiting on track.recv().
        3. Puts None sentinels in both queues so any consumers (audio_input_stream,
           _AgentAudioTrack.recv) know the bridge is done and can exit cleanly.
        """
        self._closed = True
        if self._inbound_task:
            self._inbound_task.cancel()
            try:
                await self._inbound_task
            except asyncio.CancelledError:
                pass
        await self.inbound_queue.put(None)
        await self.outbound_queue.put(None)


# ────────────────────
# OUTBOUND AUDIO TRACK
# ────────────────────


class _AgentAudioTrack(AudioStreamTrack):
    """
    aiortc-compatible audio track that delivers the agent's voice to the browser.

    This is a standard aiortc MediaStreamTrack subclass. aiortc calls recv()
    on it in a loop to get frames to send to the browser via the WebRTC
    peer connection. We provide exactly one 20ms frame per call, paced to
    the correct clock rate.

    Pipeline (per recv() call):
      1. Check timing - sleep until the next 20ms deadline
      2. Drain outbound_queue into _buf (resampling 24kHz -> 48kHz as we go)
      3. Slice exactly one 20ms frame from _buf (960 samples × 2 bytes = 1920 bytes)
      4. Pad with silence if we don't have enough data (agent hasn't responded yet)
      5. Build and return an av.AudioFrame

    The pts-based pacing clock mirrors aiortc's own AudioStreamTrack base class.
    We reset it (via clear_buf) between turns to prevent drift accumulation.
    """

    def __init__(self, *, queue: asyncio.Queue, session_id: str) -> None:
        super().__init__()
        self._queue = queue
        self._session_id = session_id
        self._sample_rate = _WEBRTC_SAMPLE_RATE  # 48000 - what WebRTC expects
        self._samples_per_frame = int(
            _WEBRTC_SAMPLE_RATE * _CHUNK_DURATION
        )  # 960 samples/frame
        self._resampler = av.AudioResampler(
            format="s16", layout="mono", rate=_WEBRTC_SAMPLE_RATE  # 48kHz output
        )
        self._buf = bytearray()  # ring buffer of resampled 48kHz s16 PCM
        self._pts = 0  # presentation timestamp, increments by samples_per_frame
        self._start: Optional[float] = None  # wall clock anchor for pacing

    @property
    def has_buffered_audio(self) -> bool:
        """
        Returns True if there is resampled audio waiting in _buf to be
        delivered to the browser.

        Used by InterviewConnection._on_turn_complete() to know when it's
        safe to call clear_outbound_queue() - we wait until this is False,
        meaning all buffered audio has been consumed by recv() and sent to
        the browser before we reset the resampler.
        """
        return len(self._buf) > 0

    def clear_buf(self) -> None:
        """
        Discards all buffered audio, flushes and resets the resampler,
        and resets the pts clock to zero.

        Called by AudioBridge.clear_outbound_queue() - either during an
        interrupt (immediate stop) or at end-of-turn cleanup (safe reset).

        WHY REINSTANTIATE THE RESAMPLER?
        av.AudioResampler holds internal state (filter graph, delay compensation
        buffers). Flushing with resample(None) helps but doesn't guarantee
        complete state reset. Reinstantiating is the only way to guarantee
        the next turn starts with a clean resampler.

        WHY RESET pts AND _start?
        Each turn is effectively a new audio stream. Resetting pts to 0 and
        _start to None means the pacing clock restarts from zero at the
        first recv() of the new turn, preventing timestamp drift.
        """
        self._buf.clear()
        # Flush any samples held inside the resampler's internal state
        try:
            flush_frames = self._resampler.resample(None)  # None = flush
            # discard - we don't want the flushed frames, just clearing state
        except Exception:
            pass
        # Reinstantiate to guarantee clean state
        self._resampler = av.AudioResampler(
            format="s16", layout="mono", rate=_WEBRTC_SAMPLE_RATE
        )
        # Reset pts and start so the pacing clock restarts cleanly for the next turn
        self._pts = 0
        self._start = None  # will be re-anchored on next recv() call

    async def recv(self) -> av.AudioFrame:
        """
        Called by aiortc's send loop to get the next audio frame to deliver
        to the browser. Must return exactly one 20ms frame per call.

        PACING (timing) 
        On the first call: anchor _start to now.
        On subsequent calls: compute when the next frame is due (based on pts),
        and sleep until that deadline. This produces a steady 50fps (20ms/frame)
        cadence that matches WebRTC's expectation.

        Without this pacing, frames would be delivered as fast as the queue
        fills, causing the browser to receive bursts of audio which it can't
        play in real-time - resulting in choppy or fast-forwarded speech.

        QUEUE DRAIN
        We drain the queue greedily (get_nowait() in a loop) into _buf until
        we have at least one full frame's worth of data, or the queue is empty.
        Each chunk from the queue is resampled 24kHz -> 48kHz before going in.

        SILENCE PADDING
        If after draining the queue we still don't have a full frame, we pad
        with silence. This happens between agent turns when the queue is empty
        - it keeps the WebRTC stream alive (browser expects continuous frames)
        without playing anything audible.

        FRAME CONSTRUCTION
        Build an av.AudioFrame at 48kHz mono s16 with the correct pts.
        aiortc uses this to package the audio as an Opus RTP packet and send
        it to the browser.
        """
        # Pace to exactly 20ms intervals
        if self._start is None:
            self._start = time.time()  # anchor the clock on first frame
        else:
            self._pts += self._samples_per_frame
            deadline = self._start + (self._pts / self._sample_rate)
            wait = deadline - time.time()
            if wait > 0:
                await asyncio.sleep(wait)

        # Drain queue into buffer until we have a full frame 
        target = (
            self._samples_per_frame * 2
        )  # bytes needed (960 samples × 2 bytes = 1920)

        while len(self._buf) < target:
            try:
                pcm_24k = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break  # not enough data - will pad with silence below

            if pcm_24k is None:
                raise Exception("AudioBridge closed")  # sentinel - bridge is done

            # Resample from 24kHz (Gemini output) -> 48kHz (WebRTC expected)
            n = len(pcm_24k) // 2  # number of samples in the 24kHz chunk
            in_frame = av.AudioFrame(format="s16", layout="mono", samples=n)
            in_frame.planes[0].update(pcm_24k)
            in_frame.sample_rate = _OUTPUT_SAMPLE_RATE  # 24000 input
            in_frame.time_base = fractions.Fraction(1, _OUTPUT_SAMPLE_RATE)
            in_frame.pts = 0
            for rf in self._resampler.resample(in_frame):
                self._buf.extend(
                    bytes(rf.planes[0])
                )  # append resampled 48kHz PCM to buf

        # Slice exactly one frame, pad with silence if needed
        if len(self._buf) >= target:
            out_pcm = bytes(self._buf[:target])
            del self._buf[:target]  # consume from front of ring buffer
        else:
            # Not enough data - deliver silence for this frame
            silence_needed = target - len(self._buf)
            out_pcm = bytes(self._buf) + b"\x00\x00" * (silence_needed // 2)
            self._buf.clear()

        # Build the av.AudioFrame and return to aiortc
        frame = av.AudioFrame(
            format="s16", layout="mono", samples=self._samples_per_frame
        )
        frame.planes[0].update(out_pcm)
        frame.sample_rate = self._sample_rate  # 48000
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        frame.pts = self._pts
        return frame
