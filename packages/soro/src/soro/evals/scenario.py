"""
Scenarios: a scripted caller, the tools on offer, and what a good agent does.

A Scenario is provider-neutral. ScenarioRunner plays the caller's side against a
real VoiceAgentRuntime on whatever adapter it is given, through a TracingAdapter,
so the same scenario scores the scripted baseline, Gemini, OpenAI or the
composed pipeline, and the numbers are comparable.

Caller turns are text (sent with send_client_content, which every adapter
supports, so they run live) or audio (synthetic frames, or real ones loaded from
a WAV). Synthetic audio only means something to the ScriptedAdapter, so a
scenario that needs it sets live=False and live runs skip it.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional, Sequence

from soro.connectors.base import ToolPair, registry_from_pairs
from soro.connectors.functions import functions
from soro.evals.audio_fixtures import FRAME_MS, speech_frames
from soro.evals.scripted_adapter import Event, speech
from soro.evals.trace import Trace, TracingAdapter
from soro.ports import AdapterCapabilities, LiveSessionPort
from soro.runtime.runtime import RuntimeCallbacks, VoiceAgentRuntime
from soro.tools import ToolSpec


@dataclass(frozen=True)
class CallerTurn:
    """
    One thing the caller says. Exactly one of text, audio_s or audio.

    barge_in: start as soon as the agent begins speaking its reply to the
        previous turn, instead of waiting for it to finish.
    """

    text: Optional[str] = None
    audio_s: float = 0.0
    audio: Optional[tuple[bytes, ...]] = None
    barge_in: bool = False

    def frames(self, seed: int) -> list[bytes]:
        if self.audio is not None:
            return list(self.audio)
        if self.audio_s > 0:
            return speech_frames(self.audio_s, random.Random(seed))
        return []


@dataclass(frozen=True)
class ExpectedCall:
    """A tool call that must happen. args is a subset match; a compiled regex value is searched."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)

    def matches(self, name: str, args: dict[str, Any]) -> bool:
        if name != self.name:
            return False
        for key, want in self.args.items():
            if key not in args:
                return False
            got = args[key]
            if isinstance(want, re.Pattern):
                if not want.search(str(got)):
                    return False
            elif got != want:
                return False
        return True


@dataclass(frozen=True)
class Scenario:
    """
    expected_calls: must occur in this order (other calls may sit between them).
    forbidden_calls: must never occur.
    each_preceded_by: {"record_question": "persist_answer"} means every
        record_question after the first needs a persist_answer since the previous
        one. This is the "never advance before saving the answer" rule.
    transcript_patterns: regexes that must all match the agent's spoken transcript.
    script: the ScriptedAdapter's responses, one per user turn (the opening
        message counts as the first).
    live: whether the scenario means anything on a real provider.
    """

    name: str
    prompt: str
    turns: tuple[CallerTurn, ...]
    description: str = ""
    tools: tuple[ToolSpec | Callable, ...] = ()
    tool_results: dict[str, dict] = field(default_factory=dict)
    opening_message: Optional[str] = None
    resume_message: Optional[str] = None
    expected_calls: tuple[ExpectedCall, ...] = ()
    forbidden_calls: tuple[str, ...] = ()
    each_preceded_by: dict[str, str] = field(default_factory=dict)
    transcript_patterns: tuple[str, ...] = ()
    script: tuple[tuple[Event, ...], ...] = ()
    live: bool = True

    async def tool_pairs(self) -> list[ToolPair]:
        specs = [t for t in self.tools if isinstance(t, ToolSpec)]
        fns = [t for t in self.tools if not isinstance(t, ToolSpec)]
        pairs: list[ToolPair] = [(s, self._canned(s.name)) for s in specs]
        if fns:
            pairs.extend(await functions(*fns).tools())
        return pairs

    def _canned(self, name: str):
        result = self.tool_results.get(name, {"success": True})

        async def handle(args: dict[str, Any]) -> dict[str, Any]:
            return dict(result)

        return handle


@dataclass
class ScenarioRun:
    """The raw outcome of one scenario on one adapter. metrics.py turns it into numbers."""

    scenario: Scenario
    provider: str
    trace: Trace
    capabilities: AdapterCapabilities
    end_reason: Optional[str] = None
    error: Optional[str] = None
    timeouts: int = 0


class ScenarioRunner:
    def __init__(
        self,
        *,
        turn_timeout_s: float = 20.0,
        session_timeout_s: float = 120.0,
        settle_s: float = 0.3,
        seed: int = 7,
    ) -> None:
        """
        turn_timeout_s: how long to wait for the agent to finish a reply.
        settle_s: quiet time after a reply before the caller speaks again, so a
            provider that answers in several responses (OpenAI after a tool call)
            is not talked over by accident.
        """
        self.turn_timeout_s = turn_timeout_s
        self.session_timeout_s = session_timeout_s
        self.settle_s = settle_s
        self.seed = seed

    async def run(
        self, scenario: Scenario, adapter: LiveSessionPort, provider: str = ""
    ) -> ScenarioRun:
        tap = TracingAdapter(adapter)
        run = ScenarioRun(
            scenario, provider or type(adapter).__name__, tap.trace, adapter.capabilities
        )

        async def discard(*_: Any) -> None:
            return None

        runtime = VoiceAgentRuntime(
            adapter=tap,
            system_prompt=scenario.prompt,
            tools=registry_from_pairs(await scenario.tool_pairs()),
            audio_input_stream=self._caller(scenario, tap, run),
            callbacks=RuntimeCallbacks(on_audio_output=discard),
            opening_message=scenario.opening_message,
            resume_message=scenario.resume_message,
        )
        try:
            await asyncio.wait_for(runtime.run(), self.session_timeout_s)
        except asyncio.TimeoutError:
            run.error = f"session exceeded {self.session_timeout_s}s"
        except Exception as exc:  # a provider failure is a result to report, not a crash
            run.error = f"{type(exc).__name__}: {exc}"
        run.end_reason = runtime.end_reason
        return run

    # ── The caller

    async def _caller(
        self, scenario: Scenario, tap: TracingAdapter, run: ScenarioRun
    ) -> AsyncIterator[bytes]:
        trace = tap.trace
        await trace.wait_for(
            lambda: trace.first("mark", "session_open") is not None, self.turn_timeout_s
        )
        since = 0
        turns = scenario.turns
        if scenario.opening_message is not None and not (turns and turns[0].barge_in):
            await self._await_reply(trace, since, run)

        for idx, turn in enumerate(turns):
            if turn.barge_in:
                started = await trace.wait_for(
                    lambda: trace.first("in", "audio", since) is not None, self.turn_timeout_s
                )
                if not started:
                    run.timeouts += 1
            await trace.add("mark", "caller_turn_start", {"turn": idx, "barge_in": turn.barge_in})
            if turn.text is not None:
                await tap.send_client_content(turn.text)
            for frame in turn.frames(self.seed + idx):
                yield frame
                await asyncio.sleep(FRAME_MS / 1000)
            end = await trace.add(
                "mark", "caller_turn_end", {"turn": idx, "barge_in": turn.barge_in}
            )
            since = end.i
            next_barges = idx + 1 < len(turns) and turns[idx + 1].barge_in
            if not next_barges:
                await self._await_reply(trace, since, run)
        await trace.add("mark", "caller_done")

    async def _await_reply(self, trace: Trace, since: int, run: ScenarioRun) -> None:
        """
        The reply is over when a turn_complete arrives after `since` and after the
        last tool response (a provider may finish one response, take the tool
        result, and speak again), followed by settle_s of quiet.
        """

        def replied() -> bool:
            done = trace.select("in", "turn_complete", since)
            if not done:
                return False
            tools = trace.select("out", "tool_response", since)
            return not tools or done[-1].i > tools[-1].i

        if not await trace.wait_for(replied, self.turn_timeout_s):
            run.timeouts += 1
            await trace.add("mark", "timeout")
            return
        while True:
            seen = len(trace.events)
            await asyncio.sleep(self.settle_s)
            if len(trace.events) == seen:
                return
            if not replied():  # a follow-up response started: wait for it to finish too
                if not await trace.wait_for(replied, self.turn_timeout_s):
                    run.timeouts += 1
                    return


# ── Built-in scenarios


def _call(call_id: str, name: str, **args: Any) -> Event:
    return ("tool_call", {"id": call_id, "name": name, "args": args})


NOTE_TOOLS = (
    ToolSpec(
        "save_note",
        "Save a note for the user.",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
)

INTERVIEW_TOOLS = (
    ToolSpec(
        "record_question",
        "Record the question you are about to ask.",
        {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    ),
    ToolSpec(
        "persist_answer",
        "Save the candidate's answer to the current question.",
        {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
    ),
    ToolSpec("complete_interview", "End the interview once every question is answered."),
)

BUILTIN_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="note_taker",
        description="Greets, then saves the note the caller dictates.",
        prompt="You are a friendly note-taking assistant. Greet the user briefly. "
        "When they ask you to remember something, call save_note with it, then confirm in one sentence.",
        opening_message="The user has just joined the call.",
        turns=(CallerTurn(text="Please save a note that says buy milk."),),
        tools=NOTE_TOOLS,
        expected_calls=(ExpectedCall("save_note", {"text": re.compile("milk", re.I)}),),
        transcript_patterns=(r"(?i)\b(hi|hello|hey|welcome|good (morning|afternoon|evening))\b",),
        script=(
            (*speech(0.4), ("text", "Hi! What would you like me to note down?")),
            (_call("c1", "save_note", text="buy milk"), *speech(0.3), ("text", "Saved: buy milk.")),
        ),
    ),
    Scenario(
        name="interview_order",
        description="Two-question interview; every answer is saved before the next question.",
        prompt="You are a job interviewer. Before asking each question, call record_question with it. "
        "After the candidate answers, call persist_answer with their answer before saying anything else. "
        "Ask exactly two short questions, then call complete_interview and say goodbye.",
        opening_message="The candidate has joined and is ready.",
        turns=(
            CallerTurn(text="I have five years of Python experience, mostly backend work."),
            CallerTurn(text="I led a small team that split a monolith into services."),
        ),
        tools=INTERVIEW_TOOLS,
        expected_calls=(
            ExpectedCall("record_question"),
            ExpectedCall("persist_answer", {"answer": re.compile("python", re.I)}),
            ExpectedCall("record_question"),
            ExpectedCall("persist_answer", {"answer": re.compile("team|monolith|services", re.I)}),
            ExpectedCall("complete_interview"),
        ),
        each_preceded_by={"record_question": "persist_answer"},
        script=(
            (
                _call("q1", "record_question", question="Tell me about your Python experience."),
                *speech(0.3),
                ("text", "Tell me about your Python experience."),
            ),
            (
                _call("a1", "persist_answer", answer="Five years of Python, mostly backend."),
                _call("q2", "record_question", question="Describe a project you led."),
                *speech(0.3),
                ("text", "Thanks. Describe a project you led."),
            ),
            (
                _call(
                    "a2", "persist_answer", answer="Led a team splitting a monolith into services."
                ),
                _call("done", "complete_interview"),
                *speech(0.2),
                ("text", "Thank you, goodbye."),
            ),
        ),
    ),
    Scenario(
        name="spoken_turn",
        description="A spoken caller turn: latency includes the adapter's end-of-turn detection.",
        prompt="You are a helpful assistant.",
        opening_message="The user has joined.",
        turns=(CallerTurn(audio_s=0.6),),
        script=((*speech(0.3),), (*speech(0.3), ("text", "Sure, I can help with that."))),
        live=False,
    ),
    Scenario(
        name="barge_in",
        description="The caller talks over a long greeting; the agent must stop and yield.",
        prompt="You are a helpful assistant.",
        opening_message="The user has joined.",
        turns=(CallerTurn(audio_s=0.3, barge_in=True),),
        script=(
            (*speech(2.0), ("text", "Hello and welcome, let me tell you everything...")),
            (*speech(0.3), ("text", "Sorry, go ahead.")),
        ),
        live=False,
    ),
    Scenario(
        name="reconnect",
        description="The provider connection drops mid-reply and resumes; the turn must still complete.",
        prompt="You are a helpful assistant.",
        opening_message="The user has joined.",
        turns=(CallerTurn(text="What can you do?"),),
        script=(
            (*speech(0.2),),
            (
                *speech(0.1),
                ("session_resumed", {"reason": "eval", "restarted": False}),
                *speech(0.2),
                ("text", "I can take notes and answer questions."),
            ),
        ),
        live=False,
    ),
)


def get_scenarios(names: Sequence[str] | None = None) -> list[Scenario]:
    if not names:
        return list(BUILTIN_SCENARIOS)
    by_name = {s.name: s for s in BUILTIN_SCENARIOS}
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise ValueError(f"Unknown scenarios {unknown}. Available: {sorted(by_name)}")
    return [by_name[n] for n in names]
