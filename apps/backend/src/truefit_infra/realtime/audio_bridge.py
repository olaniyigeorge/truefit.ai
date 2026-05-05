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
from typing import AsyncIterator, Callable, Optional
import struct
import math

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
        self._on_activity_start: Optional[Callable] = None
        self._on_activity_end: Optional[Callable] = None
        self._last_activity_start: float = 0.0
        self._last_activity_end: float = 0.0
        self._activity_send_lock = asyncio.Lock()


        self._vad_is_speaking = False
        self._vad_consecutive_silent = 0
        self._vad_waiting_for_response = False  # KEY: locked after ActivityEnd
        self._vad_response_timeout_task: Optional[asyncio.Task] = None
        self._last_activity_start: float = 0.0
        self._last_activity_end: float = 0.0

        self._vad_unlock_task: Optional[asyncio.Task] = None

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

        
    def _schedule_vad_unlock_timeout(self, timeout_seconds: float = 10.0) -> None:
        """Safety net: force-unlock VAD if Gemini never fires turn_complete."""
        if self._vad_response_timeout_task:
            self._vad_response_timeout_task.cancel()
        
        async def _unlock_after_timeout():
            await asyncio.sleep(timeout_seconds)
            if self._vad_waiting_for_response:
                logger.warning("[Bridge] VAD unlock timeout — forcing unlock (Gemini may have dropped the turn)")
                self.on_agent_responded()
        
        self._vad_response_timeout_task = asyncio.create_task(_unlock_after_timeout())        

    def _arm_vad_unlock_timeout(self, timeout: float = 12.0) -> None:
        """
        If Gemini doesn't fire turn_complete within `timeout` seconds,
        force-unlock the VAD so the candidate can speak again.
        """
        if self._vad_unlock_task and not self._vad_unlock_task.done():
            self._vad_unlock_task.cancel()

        async def _unlock():
            await asyncio.sleep(timeout)
            if self._vad_waiting_for_response:
                logger.warning("[Bridge] VAD deadlock timeout — force-unlocking VAD")
                self.on_agent_responded()

        self._vad_unlock_task = asyncio.create_task(_unlock())


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

        # Silence detection state
        SPEECH_THRESHOLD = 400    # Peak amplitude to trigger START (tune upward if noisy)
        SILENCE_THRESHOLD = 200   # Peak amplitude to count as silence
        SILENCE_DURATION = 0.8    # Seconds of silence before ActivityEnd
        silence_samples = int(_SAMPLE_RATE * SILENCE_DURATION)
        _TIMEOUT_SILENCE_INCREMENT = int(_SAMPLE_RATE * 1.0)  # 1s timeout → credit 1s of silence samples
        

            
        try:
            while not self._closed:
                try:
                    frame = await asyncio.wait_for(track.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Track delivered no frame for 1s.
                    # Treat as silence for VAD — this fires ActivityEnd when the
                    # candidate has stopped and the WebRTC track goes quiet.
                    if self._vad_is_speaking and self._mic_open.is_set():
                        self._vad_consecutive_silent += _TIMEOUT_SILENCE_INCREMENT
                        if self._vad_consecutive_silent >= silence_samples:
                            now = time.monotonic()
                            if now - self._last_activity_end > 0.5:
                                self._vad_is_speaking = False
                                self._vad_consecutive_silent = 0
                                self._vad_waiting_for_response = True
                                self._last_activity_end = now
                                logger.info("[Bridge] VAD: speech END (track quiet) — waiting for Gemini")
                                if self._on_activity_end:
                                    asyncio.create_task(
                                        self._safe_callback(self._on_activity_end)
                                    )
                    continue
                except Exception as e:
                    logger.warning(f"[{self._ctx.session_id}] Inbound track error: {e}")
                    break

                # MIC GATE: discard frame if mic is closed (agent is speaking
                # or we're in the transition window)
                if not self._mic_open.is_set():
                    # Mic closed — reset speaking state so we start fresh next turn
                    if self._vad_is_speaking:
                        self._vad_is_speaking = False
                        self._vad_consecutive_silent = 0
                    continue  # discard frame entirely, don't even resample

                resampled_frames = resampler.resample(frame)
                for rf in resampled_frames:
                    pcm_bytes = bytes(rf.planes[0])
                    chunk_size = (
                        int(_SAMPLE_RATE * _CHUNK_DURATION) * _SAMPLE_WIDTH
                    )  # 640 bytes
                    for i in range(0, len(pcm_bytes), chunk_size):
                        chunk = pcm_bytes[i : i + chunk_size]
                        
                        # Only enqueue full 20ms chunks
                        if len(chunk) != chunk_size:
                            continue
 
                        # ECHO SUPPRESSION: drop chunk during cooldown window
                        if time.monotonic() < self._speaking_cooldown_until:
                            continue

                        # Fast peak detection — sample every 8th s16 value
                        # Much faster than full RMS, good enough for VAD
                        peak = max(
                            abs(int.from_bytes(chunk[j:j+2], 'little', signed=True))
                            for j in range(0, min(len(chunk), 64), 2)
                        )

                        if peak > SPEECH_THRESHOLD:
                            self._vad_consecutive_silent = 0
                            # Only fire ActivityStart if:
                            # - not already speaking
                            # - NOT waiting for Gemini to respond (key lock!)
                            # - debounce ok
                            if (not self._vad_is_speaking
                                    and not self._vad_waiting_for_response):
                                now = time.monotonic()
                                if now - self._last_activity_start > 0.5:
                                    self._vad_is_speaking = True
                                    self._last_activity_start = now
                                    logger.info("[Bridge] VAD: speech START")
                                    if self._on_activity_start:
                                        asyncio.create_task(
                                            self._safe_callback(self._on_activity_start)
                                        )
                        else:
                            if self._vad_is_speaking:
                                self._vad_consecutive_silent += chunk_size // _SAMPLE_WIDTH
                                if self._vad_consecutive_silent >= silence_samples:
                                    now = time.monotonic()
                                    if now - self._last_activity_end > 0.5:
                                        self._vad_is_speaking = False
                                        self._vad_consecutive_silent = 0
                                        self._vad_waiting_for_response = True  # LOCK
                                        self._last_activity_end = now
                                        logger.info("[Bridge] VAD: speech END — waiting for Gemini")
                                        if self._on_activity_end:
                                            asyncio.create_task(
                                                self._safe_callback(self._on_activity_end)
                                            )

                        # Enqueue chunk regardless     
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

    async def _safe_callback(self, cb) -> None:
        """Fire a VAD callback, silently swallow closed-session errors."""
        try:
            await cb()
        except Exception as e:
            logger.debug(f"[Bridge] VAD callback swallowed: {e}")
    
    def on_agent_responded(self) -> None:
        """
        Called when Gemini's turn_complete fires — unlocks the VAD so the
        candidate can trigger ActivityStart for the next answer.
        """
        logger.info("[Bridge] VAD unlocked — Gemini responded, mic ready for candidate")
        self._vad_waiting_for_response = False
        self._vad_is_speaking = False
        self._vad_consecutive_silent = 0


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
            logger.debug(f"[AudioBridge] Queueing {len(pcm_bytes)} bytes of agent audio")
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

    PIPELINE (per recv() call):
      1. Sleep until the next 20ms wall-clock deadline (pacing)
      2. Pull ONE chunk from outbound_queue (blocking with short timeout)
      3. Resample that chunk 24kHz -> 48kHz and append to _buf
      4. Slice exactly 1920 bytes (one 20ms frame at 48kHz s16 mono) from _buf
      5. Pad with silence if _buf doesn't have enough yet
      6. Build and return an av.AudioFrame

    WHY ONE CHUNK PER recv() CALL, NOT A GREEDY DRAIN?
    The greedy drain (pulling the entire queue into _buf in one call) causes
    the resampler to receive large irregular bursts and produce proportionally
    large output bursts. Since recv() is called every 20ms, one 20ms input
    chunk per call keeps the resampler operating on uniformly-sized inputs,
    producing uniformly-sized outputs, and the pacing clock stays accurate.

    WHY av.AudioResampler WITH frame_size?
    libswresample (underneath av.AudioResampler) has an internal ring buffer.
    Without a fixed output frame_size, it can accumulate samples and release
    them in bursts whose size depends on the ratio of input to output sample
    rate and the internal buffer fill level. Passing frame_size=960 (20ms at
    48kHz) forces it to emit exactly 960 samples per output frame, making
    the resampler behave as a proper stream converter rather than a bursty
    block converter.

    WHY NOT RESET _pts AND _start IN clear_buf()?
    The pacing clock anchors to wall-clock time at the first recv() call and
    advances by exactly one frame per call thereafter. If _start is reset to
    None, the next recv() re-anchors to the current wall-clock time, which
    means all the accumulated pts offset since session start is lost. Every
    deadline computed after the reset is in the past (because pts is 0 but
    real time has advanced), so wait is always negative, asyncio.sleep(0) is
    called, and recv() spins as fast as the event loop allows — draining the
    queue faster than real-time and causing the audio loop.
    """

    def __init__(self, *, queue: asyncio.Queue, session_id: str) -> None:
        super().__init__()
        self._queue = queue
        self._session_id = session_id
        self._sample_rate = _WEBRTC_SAMPLE_RATE        # 48000Hz output to WebRTC
        self._samples_per_frame = int(
            _WEBRTC_SAMPLE_RATE * _CHUNK_DURATION      # 960 samples = 20ms at 48kHz
        )
        # frame_size=960 forces libswresample to emit exactly one 20ms frame
        # per resample() call, preventing burst output that causes audio loops.
        self._resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=_WEBRTC_SAMPLE_RATE,
            frame_size=self._samples_per_frame,
        )
        self._buf = bytearray()   # accumulator for resampled 48kHz s16 PCM
        self._pts: int = 0        # output presentation timestamp, advances by 960 per frame
        self._start: Optional[float] = None   # wall-clock anchor, set on first recv()
        self._input_pts: int = 0  # input pts fed to resampler, advances by input samples

    @property
    def has_buffered_audio(self) -> bool:
        """
        True if resampled audio is waiting in _buf.
        Used by _on_turn_complete() to know when the current turn's audio
        has fully drained out of the track before resetting the resampler.
        """
        return len(self._buf) > 0

    def clear_buf(self) -> None:
        """
        Discards buffered audio and resets the resampler for the next turn.
        Called by AudioBridge.clear_outbound_queue() at end-of-turn or interrupt.

        WHAT IS RESET:
          _buf        — discard any partially-played audio from the old turn
          _resampler  — reinstantiate to guarantee clean internal state; the
                        old instance may hold partially-compensated delay frames
                        from the previous turn that would corrupt the next one
          _input_pts  — reset to 0 because the new resampler has no history;
                        its timeline starts fresh

        WHAT IS NOT RESET:
          _pts and _start — the output pacing clock is NOT reset. It must remain
          continuous across turns. If reset, every deadline after the reset is
          computed relative to a new _start anchored at the reset moment, but
          _pts would be 0 while real time has advanced by minutes — so every
          deadline is instantly in the past, wait is always negative, and recv()
          spins without sleeping, consuming the queue faster than real-time.
        """
        self._buf.clear()
        try:
            self._resampler.resample(None)  # flush internal libswresample buffers
        except Exception:
            pass
        # Reinstantiate — the only guaranteed way to get a clean resampler state
        self._resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=_WEBRTC_SAMPLE_RATE,
            frame_size=self._samples_per_frame,
        )
        self._input_pts = 0
        # _pts and _start deliberately NOT reset — see docstring above

    async def recv(self) -> av.AudioFrame:
        """
        Called by aiortc every ~20ms to get the next audio frame for the browser.

        ──────────────────
        SECTION 1: PACING
        ──────────────────
        recv() must return exactly one frame every 20ms. aiortc does not
        enforce timing on its own — it calls recv() and immediately uses
        whatever comes back. If recv() returns too fast, frames pile up in
        the browser's jitter buffer and audio plays back at higher-than-normal
        speed. If it returns too slow, there are gaps and stutters.

        We implement pacing with a simple wall-clock anchor:
          - On the first call, record _start = time.time() and use pts=0.
          - On every subsequent call, advance _pts by 960 (one frame's worth
            of samples at 48kHz), compute the wall-clock deadline as:
              deadline = _start + (_pts / 48000)
            and sleep until that deadline.

        This produces a steady 20ms cadence regardless of how long the queue
        drain and resampling take (as long as they complete in under 20ms,
        which they always do for small inputs).

        Why _pts / sample_rate and not just asyncio.sleep(0.02)?
        Cumulative drift. asyncio.sleep(0.02) drifts by several milliseconds
        per call due to event loop scheduling jitter. Over a 60-second interview
        that's hundreds of milliseconds of drift. The pts-based approach
        self-corrects on every frame — if a frame runs long, the next sleep
        is shorter to compensate.

        ────────────────────────────────────────────
        SECTION 2: QUEUE DRAIN (ONE CHUNK PER CALL)
        ────────────────────────────────────────────
        We pull at most one chunk from the queue per recv() call. This is
        intentional and critical. The previous implementation used a greedy
        drain (loop until _buf >= target), which caused two problems:

          a) The resampler received large irregular inputs and produced large
             irregular outputs, filling _buf with many seconds of audio at once.
             recv() then sliced through this in subsequent calls without ever
             sleeping (because the pacing deadline was already past), playing
             the audio at ~48x normal speed.

          b) Even with correct pacing, pulling the entire queue in one call
             means _buf can grow to 10+ seconds of audio. Subsequent calls
             find _buf already full, skip the queue entirely, and the pacing
             clock drifts relative to the actual audio content.

        One chunk per call means _buf grows by at most one resampled chunk
        (≈1920 bytes = 20ms) per recv() call, keeping _buf shallow and the
        resampler operating on uniform 20ms inputs.

        We use asyncio.wait_for with a short timeout instead of get_nowait()
        so that when the queue is empty (silence between turns) recv() still
        returns on schedule rather than blocking indefinitely.

        ──────────────────────
        SECTION 3: RESAMPLING
        ──────────────────────
        Input:  24kHz mono s16 PCM from Gemini (variable chunk sizes)
        Output: 48kHz mono s16 PCM for WebRTC (fixed 960 samples = 1920 bytes)

        The resampler is configured with frame_size=960, which forces
        libswresample to emit exactly 960 output samples per resample() call.
        This prevents the burst-output behaviour of an unconstrained resampler.

        input_pts is tracked and incremented by the number of input samples
        on each call. This gives libswresample a continuous timeline, which
        it uses for its compensation calculations. Without a monotonically
        advancing pts, some versions of libswresample re-initialise their
        internal state on each call, producing the burst output.

        ───────────────────────
        SECTION 4: SLICE / PAD
        ───────────────────────
        After resampling (or if the queue was empty), we need exactly 1920
        bytes to fill one output frame. If _buf has >= 1920 bytes we slice.
        If not, we pad with silence. Silence padding happens during the gap
        between turns — it keeps the WebRTC stream alive without audible gaps.

        ────────────────────────
        SECTION 5: FRAME BUILD
        ────────────────────────
        We build an av.AudioFrame with the correct sample_rate, time_base,
        and pts. aiortc uses pts to sequence the RTP packets it sends to the
        browser. Incorrect pts causes the browser's jitter buffer to discard
        or reorder frames.
        """

        frame_num = getattr(self, '_frame_count', 0)
        self._frame_count = frame_num + 1

        if self._start is None:
            self._start = time.time()
        else:
            self._pts += self._samples_per_frame
            deadline = self._start + (self._pts / self._sample_rate)
            wait = deadline - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            else:
                # logger.debug(
                #     f"\n[AudioTrack/{self._session_id}] "
                #     f"frame={frame_num} | LATE by {abs(wait)*1000:.1f}ms\n"
                # )
                pass

        try:
            pcm_24k = await asyncio.wait_for(
                self._queue.get(), timeout=0.005  # 5ms - well within our 20ms budget
            )

            if pcm_24k is None:
                # logger.info(
                #     f"\n[AudioTrack/{self._session_id}]"
                #     f"frame={frame_num} | got None sentinel — bridge is CLOSED\n"
                # )
                raise Exception("AudioBridge closed")

            n_samples_in = len(pcm_24k) // 2
            in_frame = av.AudioFrame(
                format="s16", layout="mono", samples=n_samples_in
            )
            in_frame.planes[0].update(pcm_24k)
            in_frame.sample_rate = _OUTPUT_SAMPLE_RATE
            in_frame.time_base = fractions.Fraction(1, _OUTPUT_SAMPLE_RATE)
            in_frame.pts = self._input_pts
            self._input_pts += n_samples_in

            resampled_bytes = 0
            for rf in self._resampler.resample(in_frame):
                chunk = bytes(rf.planes[0])
                self._buf.extend(chunk)
                resampled_bytes += len(chunk)

        except asyncio.TimeoutError:
            # Queue empty: no audio in  this frame, will pad with silence below
            # logger.error(
            #     f"\n[AudioTrack/{self._session_id}] "
            #     f"frame={frame_num} | queue empty — will pad with silence | "
            #     f"buf={len(self._buf)}B\n"
            # )
            pass
 
        target = self._samples_per_frame * 2  # 1920 bytes

        if len(self._buf) >= target:
            out_pcm = bytes(self._buf[:target])
            del self._buf[:target]
        else:
            available = len(self._buf)
            out_pcm = bytes(self._buf) + b"\x00\x00" * ((target - available) // 2)
            self._buf.clear()
            if available > 0:
                # logger.debug(
                #     f"\n[AudioTrack/{self._session_id}] "
                #     f"frame={frame_num} | PARTIAL+PAD | "
                #     f"real={available}B silence={target - available}B\n"
                # )
                pass
            else:
                # logger.debug(
                #     f"\n[AudioTrack/{self._session_id}] "
                #     f"frame={frame_num} | FULL SILENCE\n"
                # )
                pass

        frame = av.AudioFrame(
            format="s16", layout="mono", samples=self._samples_per_frame
        )
        frame.planes[0].update(out_pcm)
        frame.sample_rate = self._sample_rate
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        frame.pts = self._pts

        return frame