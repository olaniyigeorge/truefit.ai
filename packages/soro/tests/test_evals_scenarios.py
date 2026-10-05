"""
Scenario runner end to end on the ScriptedAdapter: the built-in scenarios pass on
the baseline, and a scripted model that breaks a rule is caught.
"""

from __future__ import annotations

import asyncio

import pytest

from soro.evals import (
    BUILTIN_SCENARIOS,
    CallerTurn,
    ExpectedCall,
    Scenario,
    ScenarioRunner,
    ScriptedAdapter,
    compute_metrics,
    get_scenarios,
    run_suite,
    scorecard,
    speech,
)
from soro.evals.__main__ import main
from soro.evals.scenario import INTERVIEW_TOOLS
from soro.evals.trace import TracingAdapter
from soro.testing import FakeLiveAdapter

pytestmark = pytest.mark.unit

FAST = dict(turn_timeout_s=5.0, settle_s=0.05)


@pytest.mark.parametrize("scenario", BUILTIN_SCENARIOS, ids=lambda s: s.name)
async def test_every_builtin_scenario_passes_on_the_scripted_baseline(scenario):
    run = await ScenarioRunner(**FAST).run(scenario, ScriptedAdapter(scenario.script), "scripted")
    card = scorecard(run)
    assert card.passed, card.failures
    assert card.ttfa_ms is not None and card.ttfa_ms < 1000


async def test_spoken_turn_latency_includes_end_of_turn_detection():
    scenario = get_scenarios(["spoken_turn"])[0]
    adapter = ScriptedAdapter(scenario.script, end_of_turn_s=0.2, response_delay_s=0.05)
    m = compute_metrics(await ScenarioRunner(**FAST).run(scenario, adapter))
    [latency] = m.turn_latency_ms
    assert 230 <= latency < 1000  # silence wait + response delay, plus scheduling slack
    assert m.audio_in_s == pytest.approx(0.6, abs=0.05)


async def test_barge_in_stops_the_scripted_agent():
    scenario = get_scenarios(["barge_in"])[0]
    adapter = ScriptedAdapter(scenario.script)
    m = compute_metrics(await ScenarioRunner(**FAST).run(scenario, adapter))
    assert (m.barge_ins, m.barge_ins_handled) == (1, 1)
    assert m.audio_out_s < 1.0  # the 2s greeting was cut short


async def test_an_agent_that_skips_persist_answer_fails_the_ordering_rule():
    bad_script = (
        (("tool_call", {"id": "q1", "name": "record_question", "args": {"question": "Q1"}}), *speech(0.1)),
        (("tool_call", {"id": "q2", "name": "record_question", "args": {"question": "Q2"}}), *speech(0.1)),
    )
    scenario = Scenario(
        name="sloppy",
        prompt="p",
        opening_message="go",
        turns=(CallerTurn(text="an answer"),),
        tools=INTERVIEW_TOOLS,
        expected_calls=(ExpectedCall("persist_answer"),),
        each_preceded_by={"record_question": "persist_answer"},
        script=bad_script,
    )
    card = scorecard(await ScenarioRunner(**FAST).run(scenario, ScriptedAdapter(scenario.script)))
    assert not card.passed
    assert "record_question called again before persist_answer" in card.failures


async def test_tool_responses_reach_the_model_and_function_tools_work():
    calls = []

    def lookup(city: str) -> dict:
        """Weather lookup."""
        calls.append(city)
        return {"forecast": "sunny"}

    scenario = Scenario(
        name="fn",
        prompt="p",
        turns=(CallerTurn(text="weather?"),),
        tools=(lookup,),
        script=((("tool_call", {"id": "1", "name": "lookup", "args": {"city": "Lagos"}}), *speech(0.1)),),
    )
    adapter = ScriptedAdapter(scenario.script)
    await ScenarioRunner(**FAST).run(scenario, adapter)
    assert calls == ["Lagos"]
    assert adapter.tool_responses == [{"call_id": "1", "name": "lookup", "result": {"forecast": "sunny"}}]


async def test_a_silent_model_times_out_instead_of_hanging():
    scenario = Scenario(name="silent", prompt="p", turns=(CallerTurn(text="hello?"),))
    run = await ScenarioRunner(turn_timeout_s=0.2, settle_s=0.01).run(scenario, ScriptedAdapter(()))
    assert run.timeouts == 1 and not scorecard(run).passed


async def test_provider_errors_are_reported_not_raised():
    scenario = Scenario(name="err", prompt="p", turns=(CallerTurn(text="hi"),))
    run = await ScenarioRunner(**FAST).run(scenario, FakeLiveAdapter(events=[RuntimeError("1011")]))
    assert run.error == "RuntimeError: 1011"


async def test_tracing_adapter_records_both_directions_and_passes_through():
    inner = FakeLiveAdapter(events=[("audio", b"\x00" * 10), ("turn_complete", None)])
    tap = TracingAdapter(inner)
    async with tap.open_session("p") as session:
        await session.send_client_content(text="hi")
        await session.send_audio(b"\x00" * 4)
        received = [e async for e in session.receive()]
    assert received == [("audio", b"\x00" * 10), ("turn_complete", None)]
    kinds = [(e.direction, e.kind, e.data) for e in tap.trace.events]
    assert kinds == [
        ("mark", "session_open", None),
        ("out", "content", "hi"),
        ("out", "audio", 4),
        ("in", "audio", 10),
        ("in", "turn_complete", None),
        ("mark", "session_close", None),
    ]
    assert [e.i for e in tap.trace.events] == list(range(6))
    assert inner.content == ["hi"]


async def test_run_suite_skips_unavailable_and_scripted_only_for_live_providers():
    def broken(scenario):
        raise RuntimeError("GEMINI_API_KEY is not set")

    scenarios = get_scenarios(["note_taker", "barge_in"])
    cards = await run_suite(
        {"scripted": lambda s: ScriptedAdapter(s.script), "gemini": broken},
        scenarios, runner=ScenarioRunner(**FAST), live={"gemini"},
    )
    rows = {(c.provider, c.scenario): c for c in cards}
    assert rows[("scripted", "note_taker")].passed and rows[("scripted", "barge_in")].passed
    assert rows[("gemini", "barge_in")].skipped == "needs scripted audio"
    assert rows[("gemini", "note_taker")].skipped.startswith("unavailable")


def test_unknown_scenario_names_are_rejected():
    with pytest.raises(ValueError, match="Unknown scenarios"):
        get_scenarios(["nope"])


def test_cli_lists_and_runs(capsys):
    assert main(["scenarios", "--list"]) == 0
    assert "barge_in" in capsys.readouterr().out
    assert main(["scenarios", "-s", "note_taker"]) == 0
    assert "1/1 runs passed" in capsys.readouterr().out
    assert main(["turns", "-d", "energy"]) == 0
    assert "steady_fan" in capsys.readouterr().out
