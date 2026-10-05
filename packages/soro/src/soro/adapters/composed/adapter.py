"""
ComposedLiveAdapter: STT, an LLM and TTS behind the LiveSessionPort.

The speech-to-speech adapters hand audio to one model that hears and speaks.
This one assembles the same behaviour from parts, so open and local models fit
behind the same port the runtime already uses:

    mic PCM -> TurnDetector -> utterance -> SpeechToText -> "input_text"
            -> LanguageModel (history + tools) -> "tool_call" ... tool result ...
            -> sentences -> TextToSpeech -> "audio" / "text" -> "turn_complete"

It owns turn-taking (native_vad=True): the detector decides when the user has
finished (a caller that detects turns itself can also send send_activity_start /
send_activity_end, which are taken as hints), and speech that starts while the agent is replying is a barge-in, which
cancels the reply mid-sentence and emits "interrupted".

Known limit, by design: the LLM only sees text, so tone, hesitation and timing
are lost, unlike a native audio model. It is the trade for running free and local.

Replies are spoken sentence by sentence: a TTS worker synthesises the first
sentence while the LLM is still writing the next, so first audio arrives after
one sentence, not the whole reply.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from typing import Any, AsyncGenerator, Optional

from soro.adapters.composed.components import LanguageModel, SpeechToText, TextDelta, TextToSpeech, ToolCallRequest
from soro.audio.turn import EnergyTurnDetector, TurnDetector
from soro.ports import AdapterCapabilities, LiveSessionPort
from soro.tools import ToolSpec, normalize_tools

logger = logging.getLogger("soro.adapters.composed")

_CLOSE = object()
# A sentence ends at . ! ? (or a newline) followed by whitespace. Short fragments
# are held back so "Dr. Smith" or "1. First" are not spoken as separate sentences.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
_MIN_SENTENCE = 12


class _Ctx:
    def __init__(self, owner: "ComposedLiveAdapter") -> None:
        self._owner = owner

    async def __aenter__(self) -> "ComposedLiveAdapter":
        self._owner._start()
        return self._owner

    async def __aexit__(self, *exc_info) -> None:
        await self._owner.close()


class ComposedLiveAdapter(LiveSessionPort):
    def __init__(
        self,
        *,
        stt: SpeechToText,
        llm: LanguageModel,
        tts: TextToSpeech,
        turn_detector: Optional[TurnDetector] = None,
        input_sample_rate: int = 16_000,
        preroll_ms: int = 300,
        max_utterance_s: float = 30.0,
    ) -> None:
        """
        turn_detector: decides when the user starts and stops. Defaults to the
            energy detector; pass create_turn_detector("silero") for noisy rooms.
            Its sample rate must match input_sample_rate.
        preroll_ms: audio kept from before the detector fired "start" (it fires
            after start_ms of speech), so the first syllable reaches the STT.
        max_utterance_s: an utterance this long is cut and answered, so a
            detector stuck in "speaking" cannot hold the turn forever.
        """
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.detector: TurnDetector = turn_detector or EnergyTurnDetector()
        self._input_rate = input_sample_rate
        self._preroll_bytes = input_sample_rate * 2 * preroll_ms // 1000
        self._max_utterance_bytes = int(input_sample_rate * 2 * max_utterance_s)

        self.history: list[dict[str, Any]] = []
        self._tools: list[ToolSpec] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._open = False
        self._preroll: deque[bytes] = deque()
        self._preroll_len = 0
        self._utterance: Optional[bytearray] = None
        self._last_audio = 0.0
        self._watcher: Optional[asyncio.Task] = None
        self._reply: Optional[asyncio.Task] = None
        self._warming: Optional[asyncio.Task] = None
        self._spoke = False
        self._queued_text: list[str] = []
        self._pending_tools: dict[str, asyncio.Future] = {}

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            input_sample_rate=self._input_rate,
            output_sample_rate=self.tts.sample_rate,
            supports_images=False,
            native_vad=True,
        )

    # ── Lifecycle

    def open_session(self, system_prompt: str, tools: list | None = None) -> Any:
        self._tools = normalize_tools(tools)  # rejects duplicate names before anything starts
        self.history = [{"role": "system", "content": system_prompt}]
        return _Ctx(self)

    def _start(self) -> None:
        self._open = True
        self.detector.reset()
        self._watcher = asyncio.create_task(self._watch_silence(), name="composed-silence")
        self._warming = asyncio.create_task(self._warm_up(), name="composed-warm-up")

    async def _warm_up(self) -> None:
        """
        Load the speech models while the session opens, so the first turn does not
        pay for it (loading Whisper alone takes seconds on a CPU). Components opt in
        with an async warm_up(); a failure here is only logged, since the same
        error will surface, with context, on the first real call.
        """
        for part in (self.stt, self.tts):
            warm_up = getattr(part, "warm_up", None)
            if warm_up is None:
                continue
            try:
                await warm_up()
            except Exception as exc:
                logger.warning(f"[Composed] Warm-up of {type(part).__name__} failed: {type(exc).__name__}: {exc}")

    async def close(self) -> None:
        if not self._open:
            return
        self._open = False
        tasks = [t for t in (self._reply, self._watcher, self._warming) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for future in self._pending_tools.values():
            future.cancel()
        self._pending_tools.clear()
        self._queue.put_nowait(_CLOSE)

    async def is_healthy(self) -> bool:
        return self._open

    # ── Input

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not self._open:
            return
        self._last_audio = time.monotonic()
        if self._utterance is not None:
            self._utterance += pcm_bytes
        else:
            self._preroll.append(pcm_bytes)
            self._preroll_len += len(pcm_bytes)
            while self._preroll_len > self._preroll_bytes and len(self._preroll) > 1:
                self._preroll_len -= len(self._preroll.popleft())

        event = self.detector.process(pcm_bytes)
        if event is not None and event.kind == "start":
            await self._user_started()
        elif event is not None and event.kind == "end":
            self._user_finished()
        elif self._utterance is not None and len(self._utterance) >= self._max_utterance_bytes:
            self.detector.reset()
            self._user_finished()

    async def send_activity_start(self) -> None:
        """
        A caller that detects turns itself (such as an app's audio bridge) may say
        so. Taken as a hint: start the utterance now, with the preroll, if the
        detector has not already.
        """
        if self._open and self._utterance is None:
            await self._user_started()

    async def send_activity_end(self) -> None:
        """
        The caller's end-of-turn hint: answer now instead of waiting out this
        adapter's own silence hangover, which would add a second delay per turn.
        """
        if self._open and self._utterance is not None:
            self.detector.reset()
            self._user_finished()

    async def send_client_content(self, text: str) -> None:
        """
        A text turn. While a reply is in progress it waits its turn instead of
        cutting the agent off (a background tool result should not interrupt a
        sentence); a spoken barge-in is what interrupts.
        """
        if self._replying():
            self._queued_text.append(text)
            return
        self.history.append({"role": "user", "content": text})
        self._start_reply(None)

    async def send_tool_response(self, *, call_id: str, name: str, result: dict) -> None:
        future = self._pending_tools.pop(call_id, None)
        if future is not None and not future.done():
            future.set_result(result)

    # ── Output

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        while True:
            item = await self._queue.get()
            if item is _CLOSE:
                return
            yield item

    # ── Turn-taking

    def _replying(self) -> bool:
        return self._reply is not None and not self._reply.done()

    async def _user_started(self) -> None:
        self._utterance = bytearray(b"".join(self._preroll))
        self._preroll.clear()
        self._preroll_len = 0
        if self._replying():
            await self._interrupt()

    def _user_finished(self) -> None:
        if self._utterance is None:
            return
        audio, self._utterance = bytes(self._utterance), None
        self._start_reply(audio)

    async def _interrupt(self) -> None:
        self._queued_text.clear()  # the user is talking now; stale queued turns would talk over them
        spoke = self._spoke  # read before cancelling: the reply resets it on the way out
        self._reply.cancel()
        await asyncio.gather(self._reply, return_exceptions=True)
        if spoke:
            await self._queue.put(("interrupted", None))

    def _start_reply(self, audio: Optional[bytes]) -> None:
        self._reply = asyncio.create_task(self._run_reply(audio), name="composed-reply")

    async def _watch_silence(self) -> None:
        """
        If the mic stream pauses mid-utterance (a transport that stops sending in
        silence), the detector never sees the quiet that ends the turn. Feed it the
        elapsed silence instead.
        """
        tick = 0.05
        while True:
            await asyncio.sleep(tick)
            if self._utterance is not None and time.monotonic() - self._last_audio > tick:
                event = self.detector.advance_silence(tick)
                if event is not None and event.kind == "end":
                    self._user_finished()

    # ── A reply

    async def _run_reply(self, audio: Optional[bytes]) -> None:
        said: list[str] = []
        cancelled = False
        try:
            if audio is not None:
                text = (await self.stt.transcribe(audio, self._input_rate)).strip()
                if not text:
                    return  # noise the detector took for speech: no turn
                await self._queue.put(("input_text", text))
                self.history.append({"role": "user", "content": text})

            while True:
                text, calls = await self._speak_llm_reply(said)
                if not calls:
                    break
                await self._run_tools(text, calls, said)
            await self._queue.put(("turn_complete", None))
        except asyncio.CancelledError:
            cancelled = True
            if said:
                # Keep what was actually heard, so the model knows where it was cut off.
                self.history.append({"role": "assistant", "content": " ".join(said) + " [interrupted by the user]"})
            raise
        except Exception as exc:
            # An STT/LLM/TTS failure ends this reply, not the session: the user can
            # simply speak again. turn_complete keeps the runtime's turn state sane.
            logger.error(f"[Composed] Reply failed: {type(exc).__name__}: {exc}")
            if said:
                self.history.append({"role": "assistant", "content": " ".join(said)})
            await self._queue.put(("turn_complete", None))
        finally:
            self._spoke = False
            if not cancelled:  # every way out but a barge-in hands over to a waiting text turn
                self._start_queued()

    def _start_queued(self) -> None:
        if self._queued_text and self._open:
            text = self._queued_text.pop(0)
            self.history.append({"role": "user", "content": text})
            self._start_reply(None)

    async def _speak_llm_reply(self, said: list[str]) -> tuple[str, list[ToolCallRequest]]:
        """
        Stream one LLM message, speaking it sentence by sentence through a TTS
        worker. Returns its text and the tool calls it asked for (none when it
        just spoke, in which case the message is already in the history).
        """
        sentences: asyncio.Queue = asyncio.Queue()
        speaker = asyncio.create_task(self._speak(sentences, said), name="composed-tts")
        buffer, text, calls = "", "", []
        try:
            async for chunk in self.llm.stream(self.history, self._tools):
                if isinstance(chunk, TextDelta):
                    buffer += chunk.text
                    text += chunk.text
                    buffer = self._flush_sentences(buffer, sentences)
                elif isinstance(chunk, ToolCallRequest):
                    calls.append(chunk)
            if buffer.strip():
                sentences.put_nowait(buffer.strip())
            sentences.put_nowait(None)
            await speaker
        finally:
            if not speaker.done():
                speaker.cancel()
                await asyncio.gather(speaker, return_exceptions=True)

        if not calls:
            self.history.append({"role": "assistant", "content": text})
            said.clear()
        # With tool calls the message is appended later, together with the results
        # (_run_tools): a cancelled call must never leave a tool_call unanswered in
        # the history, which OpenAI-compatible servers reject.
        return text, calls

    @staticmethod
    def _flush_sentences(buffer: str, sentences: asyncio.Queue) -> str:
        start = 0
        for match in _SENTENCE_END.finditer(buffer):
            candidate = buffer[start:match.start()].strip()
            if len(candidate) >= _MIN_SENTENCE:
                sentences.put_nowait(candidate)
                start = match.end()
        return buffer[start:]

    async def _speak(self, sentences: asyncio.Queue, said: list[str]) -> None:
        while True:
            sentence = await sentences.get()
            if sentence is None:
                return
            await self._queue.put(("text", sentence))
            heard = False
            async for pcm in self.tts.synthesize(sentence):
                if not heard:
                    # The user heard (part of) it from the first chunk on, so it is
                    # what an interruption is recorded against.
                    said.append(sentence)
                    heard = self._spoke = True
                await self._queue.put(("audio", pcm))

    async def _run_tools(self, text: str, calls: list[ToolCallRequest], said: list[str]) -> None:
        results: list[tuple[ToolCallRequest, dict]] = []
        for call in calls:
            future = asyncio.get_running_loop().create_future()
            self._pending_tools[call.id] = future
            await self._queue.put(("tool_call", {"id": call.id, "name": call.name, "args": call.args}))
            results.append((call, await future))
        self.history.append({
            "role": "assistant",
            "content": text or None,
            "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                for c, _ in results
            ],
        })
        for call, result in results:
            self.history.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
        said.clear()
