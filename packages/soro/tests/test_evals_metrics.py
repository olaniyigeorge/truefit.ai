"""
Eval metrics on hand-built traces, so every number is exact and independent of
timing. The scenario tests cover the same code on live runs of the scripted adapter.
"""

from __future__ import annotations

import re

import pytest

from soro.evals.metrics import (
    barge_ins,
    compute_metrics,
    time_to_first_audio,
    tool_call_failures,
    turn_latencies,
)
from soro.evals.report import format_scorecards, scorecard, skipped
from soro.evals.scenario import ExpectedCall, Scenario, ScenarioRun
from soro.evals.trace import Trace, TraceEvent
from soro.ports import AdapterCapabilities

pytestmark = pytest.mark.unit


def _trace(*rows) -> Trace:
    """rows: (t, direction, kind, data)"""
    trace = Trace()
    trace.events = [TraceEvent(t, d, k, data, i) for i, (t, d, k, data) in enumerate(rows)]
    return trace


def _scenario(**kw) -> Scenario:
    return Scenario(name="s", prompt="p", turns=(), **kw)


def test_latencies_measure_from_stimulus_and_turn_end_to_first_audio():
    trace = _trace(
        (0.0, "mark", "session_open", None),
        (0.1, "out", "content", "opening"),
        (0.4, "in", "audio", 960),
        (0.5, "in", "turn_complete", None),
        (1.0, "mark", "caller_turn_end", {"turn": 0}),
        (1.25, "in", "audio", 960),
        (2.0, "mark", "caller_turn_end", {"turn": 1}),
        (2.5, "in", "audio", 960),
    )
    assert time_to_first_audio(trace) == 300.0
    assert turn_latencies(trace) == [250.0, 500.0]


def test_ttfa_without_opening_starts_at_the_first_caller_turn():
    trace = _trace((0.5, "mark", "caller_turn_end", {"turn": 0}), (0.7, "in", "audio", 10))
    assert time_to_first_audio(trace) == 200.0
    assert time_to_first_audio(_trace((0.0, "in", "audio", 10))) is None


def test_barge_in_counts_handled_within_budget_and_excludes_it_from_turn_latency():
    trace = _trace(
        (0.0, "in", "audio", 960),
        (0.2, "mark", "caller_turn_start", {"turn": 0, "barge_in": True}),
        (0.3, "in", "interrupted", None),
        (0.6, "mark", "caller_turn_end", {"turn": 0, "barge_in": True}),
        (0.7, "in", "audio", 960),
        (1.0, "mark", "caller_turn_start", {"turn": 1, "barge_in": True}),  # never yielded
    )
    assert barge_ins(trace) == (2, 1, [100.0])
    assert turn_latencies(trace) == []


def test_tool_call_correctness():
    scenario = _scenario(
        expected_calls=(ExpectedCall("record_question"),
                        ExpectedCall("persist_answer", {"answer": re.compile("python", re.I)})),
        forbidden_calls=("delete_everything",),
        each_preceded_by={"record_question": "persist_answer"},
    )
    good = [("record_question", {}), ("persist_answer", {"answer": "Python!"}), ("record_question", {})]
    assert tool_call_failures(scenario, good) == []

    skipped_save = [("record_question", {}), ("record_question", {}), ("persist_answer", {"answer": "x"})]
    failures = tool_call_failures(scenario, skipped_save)
    assert "record_question called again before persist_answer" in failures
    assert any(f.startswith("expected persist_answer with {answer~/python/}") for f in failures)

    assert tool_call_failures(scenario, [*good, ("delete_everything", {})]) == ["forbidden call delete_everything"]


def test_expected_calls_must_be_in_order():
    scenario = _scenario(expected_calls=(ExpectedCall("a"), ExpectedCall("b")))
    assert tool_call_failures(scenario, [("a", {}), ("x", {}), ("b", {})]) == []
    assert tool_call_failures(scenario, [("b", {}), ("a", {})]) == ["expected b (in order), not seen"]


def _run(trace, scenario=None, **kw) -> ScenarioRun:
    return ScenarioRun(scenario or _scenario(), "fake", trace, AdapterCapabilities(), **kw)


def test_compute_metrics_reconnects_transcript_audio_and_cost():
    trace = _trace(
        (0.0, "out", "audio", 32_000),  # 1s at 16kHz
        (0.1, "in", "text", "Hel"),
        (0.2, "in", "text", "lo there"),
        (0.3, "in", "session_resumed", {"restarted": False}),
        (0.4, "in", "audio", 48_000),  # 1s at 24kHz
        (0.5, "in", "turn_complete", None),
        (0.6, "in", "session_resumed", {"restarted": False}),  # never recovered
    )
    scenario = _scenario(transcript_patterns=(r"Hello", r"goodbye"))
    m = compute_metrics(_run(trace, scenario), cost_per_minute=0.6)
    assert m.transcript == "Hello there"
    assert m.transcript_failures == ["goodbye"]
    assert (m.reconnects, m.reconnects_recovered) == (2, 1)
    assert (m.audio_in_s, m.audio_out_s) == (1.0, 1.0)
    assert m.cost_usd == 0.02


def test_scorecard_is_strict_and_the_table_lists_failures():
    trace = _trace(
        (0.0, "out", "content", "hi"),
        (0.2, "in", "audio", 960),
        (0.3, "in", "tool_call", {"id": "1", "name": "b", "args": {}}),
    )
    scenario = _scenario(expected_calls=(ExpectedCall("a"),))
    card = scorecard(_run(trace, scenario, timeouts=1))
    assert card.passed is False and card.tool_calls_ok is False
    assert card.ttfa_ms == 200.0
    assert card.failures == ["expected a (in order), not seen", "1 reply timeout(s)"]

    clean = scorecard(_run(_trace((0.0, "out", "content", "hi"), (0.1, "in", "audio", 960))))
    assert clean.passed is True

    table = format_scorecards([card, clean, skipped("gemini", "s", "unavailable: no key")])
    assert "1/2 runs passed" in table
    assert "fake/s: expected a (in order), not seen" in table
    assert "unavailable: no key" in table


def test_session_error_fails_the_card():
    card = scorecard(_run(_trace(), error="RuntimeError: boom"))
    assert card.passed is False and card.failures[0] == "RuntimeError: boom"
