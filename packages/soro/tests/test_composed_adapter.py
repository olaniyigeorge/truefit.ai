"""
ComposedLiveAdapter on fake components: the whole event flow with no models,
no network and no audio hardware.

Most tests use a scripted detector (a frame starting with b"S" starts a turn,
b"E" ends it) so turn boundaries are exact; one test runs the real energy
detector on synthetic audio to show the default path works end to end.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from soro import Agent, SessionComplete, ToolSpec
from soro.adapters.composed import (
    ComposedLiveAdapter,
    FakeLanguageModel,
    FakeSpeechToText,
    FakeTextToSpeech,
    ToolCallRequest,
)
from soro.audio.turn import EnergyTurnConfig, EnergyTurnDetector, TurnEvent

pytestmark = pytest.mark.unit

FRAME = 640  # 20ms at 16kHz
START = b"S" + b"\x00" * (FRAME - 1)
END = b"E" + b"\x00" * (FRAME - 1)
VOICE = b"\x01\x00" * (FRAME // 2)


class ScriptedDetector:
    def __init__(self) -> None:
        self._speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def process(self, pcm: bytes) -> Optional[TurnEvent]:
        if pcm[:1] == b"S" and not self._speaking:
            self._speaking = True
            return TurnEvent("start")
        if pcm[:1] == b"E" and self._speaking:
            self._speaking = False
            return TurnEvent("end")
        return None

    def advance_silence(self, seconds: float) -> Optional[TurnEvent]:
        return None

    def reset(self) -> None:
        self._speaking = False


def _adapter(llm, stt=None, tts=None, detector=None) -> ComposedLiveAdapter:
    return ComposedLiveAdapter(
        stt=stt or FakeSpeechToText(), llm=llm, tts=tts or FakeTextToSpeech(),
        turn_detector=detector or ScriptedDetector(),
    )


async def _speak(adapter, frames=3):
    await adapter.send_audio(START)
    for _ in range(frames):
        await adapter.send_audio(VOICE)
    await adapter.send_audio(END)


async def _collect(adapter, until: str, count: int = 1, timeout: float = 2.0) -> list[tuple]:
    """Events from receive() up to and including the count-th `until` event."""
    events: list[tuple] = []
    seen = 0

    async def pull():
        nonlocal seen
        async for kind, data in adapter.receive():
            events.append((kind, data))
            if kind == until:
                seen += 1
                if seen == count:
                    return

    await asyncio.wait_for(pull(), timeout)
    return events


def _kinds(events):
    out = []
    for kind, _ in events:
        if kind == "audio" and out and out[-1] == "audio":
            continue  # collapse audio runs
        out.append(kind)
    return out


async def test_text_turn_is_spoken_sentence_by_sentence():
    llm = FakeLanguageModel([["Hello there, ", "how are you today? ", "I am ", "ready to help."]])
    tts = FakeTextToSpeech()
    adapter = _adapter(llm, tts=tts)
    async with adapter.open_session("Be kind.", tools=[ToolSpec(name="ping")]) as session:
        await session.send_client_content(text="hi")
        events = await _collect(session, "turn_complete")

    assert _kinds(events) == ["text", "audio", "text", "audio", "turn_complete"]
    assert tts.spoken == ["Hello there, how are you today?", "I am ready to help."]
    assert llm.tools_seen == [["ping"]]
    assert adapter.history == [
        {"role": "system", "content": "Be kind."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello there, how are you today? I am ready to help."},
    ]


async def test_spoken_turn_with_a_tool_call_round_trip():
    llm = FakeLanguageModel([
        ["Let me save that for you. ", ToolCallRequest("c1", "save_note", {"text": "milk"})],
        ["Saved your note about milk."],
    ])
    stt = FakeSpeechToText(["remember milk"])
    adapter = _adapter(llm, stt=stt)
    async with adapter.open_session("p", tools=[ToolSpec(name="save_note")]) as session:
        await _speak(session)
        before_tool = await _collect(session, "tool_call")
        assert _kinds(before_tool) == ["input_text", "text", "audio", "tool_call"]
        assert before_tool[0] == ("input_text", "remember milk")
        assert before_tool[-1][1] == {"id": "c1", "name": "save_note", "args": {"text": "milk"}}

        await session.send_tool_response(call_id="c1", name="save_note", result={"success": True})
        after = await _collect(session, "turn_complete")
        assert _kinds(after) == ["text", "audio", "turn_complete"]

    # The utterance reached the STT, preroll included (START + 3 voice frames + END).
    assert stt.heard == [FRAME * 5]
    second_call = llm.seen[1]
    assert second_call[-2] == {
        "role": "assistant", "content": "Let me save that for you. ",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "save_note", "arguments": '{"text": "milk"}'}}],
    }
    assert second_call[-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"success": true}'}


async def test_barge_in_cancels_the_reply_and_answers_the_new_turn():
    llm = FakeLanguageModel([
        ["This is a long answer that goes on. ", "And on and on and on. ", "And on some more."],
        ["Sure, go ahead."],
    ])
    tts = FakeTextToSpeech(delay_s=0.02)
    stt = FakeSpeechToText(["tell me everything", "wait"])
    adapter = _adapter(llm, stt=stt, tts=tts)
    async with adapter.open_session("p") as session:
        await _speak(session)
        first = await _collect(session, "audio")  # the agent has started talking
        assert first[0] == ("input_text", "tell me everything")
        await _speak(session)  # the user talks over it
        rest = await _collect(session, "turn_complete")

    kinds = _kinds(rest)
    assert kinds[kinds.index("interrupted") + 1] == "input_text"
    assert kinds.count("turn_complete") == 1  # the interrupted reply never completed
    assert ("input_text", "wait") in rest
    interrupted = [m for m in adapter.history if "[interrupted by the user]" in str(m.get("content"))]
    assert len(interrupted) == 1 and interrupted[0]["role"] == "assistant"
    assert "And on some more." not in tts.spoken


async def test_noise_with_an_empty_transcript_is_not_a_turn():
    adapter = _adapter(FakeLanguageModel([["Should not be said."]]), stt=FakeSpeechToText([""]))
    async with adapter.open_session("p") as session:
        await _speak(session)
        await session.send_client_content(text="real turn")
        events = await _collect(session, "turn_complete")
    assert events[0] == ("text", "Should not be said.")  # spoken for the text turn, not the noise
    assert [m["role"] for m in adapter.history] == ["system", "user", "assistant"]


async def test_text_arriving_mid_reply_waits_instead_of_interrupting():
    llm = FakeLanguageModel([["First reply here, quite long."], ["Second reply here."]], delay_s=0.02)
    adapter = _adapter(llm)
    async with adapter.open_session("p") as session:
        await session.send_client_content(text="one")
        await asyncio.sleep(0.005)
        await session.send_client_content(text="[tool result] search finished")
        events = await _collect(session, "turn_complete", count=2)
    assert "interrupted" not in _kinds(events)
    assert [t for k, t in events if k == "text"] == ["First reply here, quite long.", "Second reply here."]
    assert adapter.history[3] == {"role": "user", "content": "[tool result] search finished"}


async def test_a_cancelled_tool_call_leaves_no_dangling_tool_message():
    llm = FakeLanguageModel([[ToolCallRequest("c1", "slow", {})], ["ok then."]])
    adapter = _adapter(llm, stt=FakeSpeechToText(["do it", "never mind"]))
    async with adapter.open_session("p", tools=[ToolSpec(name="slow")]) as session:
        await _speak(session)
        await _collect(session, "tool_call")
        await _speak(session)  # barge in while the tool is pending
        await _collect(session, "turn_complete")
        await session.send_tool_response(call_id="c1", name="slow", result={})  # late: ignored
    assert not any("tool_calls" in m or m["role"] == "tool" for m in adapter.history)


async def test_llm_failure_ends_the_reply_not_the_session():
    class Broken(FakeLanguageModel):
        async def stream(self, messages, tools):
            raise RuntimeError("server down")
            yield  # pragma: no cover

    adapter = _adapter(Broken())
    async with adapter.open_session("p") as session:
        await session.send_client_content(text="hi")
        events = await _collect(session, "turn_complete")
        assert await session.is_healthy()
    assert events == [("turn_complete", None)]


async def test_capabilities_follow_the_tts_rate_and_duplicate_tools_are_rejected():
    adapter = _adapter(FakeLanguageModel(), tts=FakeTextToSpeech(sample_rate=22_050))
    caps = adapter.capabilities
    assert (caps.input_sample_rate, caps.output_sample_rate, caps.native_vad) == (16_000, 22_050, True)
    with pytest.raises(ValueError, match="Duplicate"):
        adapter.open_session("p", tools=[ToolSpec(name="a"), ToolSpec(name="a")])


def _loud(n):
    import math
    import random
    from array import array

    rng = random.Random(1)
    peak = 4000 * math.sqrt(3)
    return [array("h", (int(rng.uniform(-peak, peak)) for _ in range(320))).tobytes() for _ in range(n)]


async def test_energy_detector_default_path_and_silence_watchdog():
    """Real detector: speech then the mic simply stops. The watchdog must end the turn."""
    detector = EnergyTurnDetector(EnergyTurnConfig(calibration_ms=100, end_ms=200))
    stt = FakeSpeechToText(["hello"])
    adapter = _adapter(FakeLanguageModel([["Hi, nice to meet you."]]), stt=stt, detector=detector)
    async with adapter.open_session("p") as session:
        for _ in range(10):
            await session.send_audio(b"\x00\x00" * 320)  # quiet: calibrate the floor
        for frame in _loud(25):
            await session.send_audio(frame)
        # No more audio at all: only the watchdog can end this turn.
        events = await _collect(session, "turn_complete", timeout=3.0)
    assert events[0] == ("input_text", "hello")
    assert stt.heard and stt.heard[0] >= 25 * 640  # the whole utterance, plus preroll


async def test_runs_under_the_runtime_through_the_agent_facade():
    notes = []

    def save_note(text: str) -> None:
        """Save a note."""
        notes.append(text)

    def end_call() -> None:
        """End the call."""
        raise SessionComplete("bye")

    llm = FakeLanguageModel([
        ["Hi! What should I note? "],
        [ToolCallRequest("c1", "save_note", {"text": "eggs"})],
        ["Noted eggs. Goodbye now. ", ToolCallRequest("c2", "end_call", {})],
    ])
    adapter = _adapter(llm, stt=FakeSpeechToText(["note eggs"]))

    async def mic():
        await asyncio.sleep(0.1)  # let the greeting play
        for frame in (START, VOICE, VOICE, END):
            yield frame
        await asyncio.sleep(2)  # stay open; the session ends via end_call

    played = []

    async def play(pcm):
        played.append(pcm)

    agent = Agent(prompt="Take notes.", tools=[save_note, end_call], adapter=adapter,
                  opening_message="The user joined.")
    reason = await asyncio.wait_for(agent.run(audio_input_stream=mic(), on_audio_output=play), 5)
    assert reason == "bye"
    assert notes == ["eggs"]
    assert played


async def test_opening_a_session_warms_up_the_speech_models(caplog):
    class WarmSTT(FakeSpeechToText):
        warmed = asyncio.Event()

        async def warm_up(self) -> None:
            self.warmed.set()

    class BrokenWarmTTS(FakeTextToSpeech):
        async def warm_up(self) -> None:
            raise RuntimeError("voice file missing")

    stt = WarmSTT()
    adapter = _adapter(FakeLanguageModel([]), stt=stt, tts=BrokenWarmTTS())
    async with adapter.open_session("sys", []):
        await asyncio.wait_for(stt.warmed.wait(), 1.0)
        await asyncio.sleep(0)  # let the TTS warm-up run and fail
        assert await adapter.is_healthy()  # a failed warm-up does not end the session
    assert "Warm-up of BrokenWarmTTS failed" in caplog.text
