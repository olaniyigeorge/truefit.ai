"""
Metrics: what a ScenarioRun's trace says about the agent.

Every number is computed from the trace alone, so it means the same on every
provider:

- time to first audio: from the first stimulus (the opening message, or the end
  of the first caller turn) to the first audio chunk back.
- turn latency: from the end of each caller turn to the first audio of the reply.
  For spoken turns this includes end-of-turn detection, which is the point.
- barge-in: for each turn spoken over the agent, did "interrupted" arrive, and
  how fast. Handled means within BARGE_IN_BUDGET_MS.
- tool-call correctness: expected calls in order with matching args, nothing
  forbidden, ordering rules held.
- reconnect recovery: every session_resumed followed by a completed turn.
- audio seconds in and out, the basis for a cost estimate. Pricing changes too
  often to hard-code, so cost is only computed when a per-minute rate is given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

from soro.evals.scenario import Scenario, ScenarioRun
from soro.evals.trace import Trace

BARGE_IN_BUDGET_MS = 1500.0


@dataclass
class Metrics:
    ttfa_ms: Optional[float] = None
    turn_latency_ms: list[float] = field(default_factory=list)
    barge_ins: int = 0
    barge_ins_handled: int = 0
    barge_in_ms: list[float] = field(default_factory=list)
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)
    tool_failures: list[str] = field(default_factory=list)
    transcript: str = ""
    transcript_failures: list[str] = field(default_factory=list)
    reconnects: int = 0
    reconnects_recovered: int = 0
    audio_in_s: float = 0.0
    audio_out_s: float = 0.0
    cost_usd: Optional[float] = None

    @property
    def mean_turn_latency_ms(self) -> Optional[float]:
        return mean(self.turn_latency_ms) if self.turn_latency_ms else None


def _ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 1)


def time_to_first_audio(trace: Trace) -> Optional[float]:
    stimuli = [
        e
        for e in trace.events
        if (e.direction, e.kind) in (("out", "content"), ("mark", "caller_turn_end"))
    ]
    if not stimuli:
        return None
    first = trace.first("in", "audio", stimuli[0].i)
    return _ms(stimuli[0].t, first.t) if first else None


def turn_latencies(trace: Trace) -> list[float]:
    out = []
    for mark in trace.select("mark", "caller_turn_end"):
        if (mark.data or {}).get("barge_in"):
            continue  # a barge-in is measured by how fast the agent yields, below
        reply = trace.first("in", "audio", mark.i)
        if reply is not None:
            out.append(_ms(mark.t, reply.t))
    return out


def barge_ins(trace: Trace) -> tuple[int, int, list[float]]:
    starts = [
        m for m in trace.select("mark", "caller_turn_start") if (m.data or {}).get("barge_in")
    ]
    handled, latencies = 0, []
    for start in starts:
        stop = trace.first("in", "interrupted", start.i)
        if stop is not None:
            ms = _ms(start.t, stop.t)
            latencies.append(ms)
            handled += ms <= BARGE_IN_BUDGET_MS
    return len(starts), handled, latencies


def tool_call_failures(scenario: Scenario, calls: list[tuple[str, dict]]) -> list[str]:
    failures: list[str] = []

    pending = list(scenario.expected_calls)
    for name, args in calls:
        if pending and pending[0].matches(name, args):
            pending.pop(0)
    for missing in pending:
        detail = f" with {_show(missing.args)}" if missing.args else ""
        failures.append(f"expected {missing.name}{detail} (in order), not seen")

    for name in scenario.forbidden_calls:
        if any(n == name for n, _ in calls):
            failures.append(f"forbidden call {name}")

    for later, required in scenario.each_preceded_by.items():
        seen_later, satisfied = False, False
        for name, _ in calls:
            if name == required:
                satisfied = True
            elif name == later:
                if seen_later and not satisfied:
                    failures.append(f"{later} called again before {required}")
                    break
                seen_later, satisfied = True, False
    return failures


def _show(args: dict) -> str:
    return (
        "{"
        + ", ".join(
            f"{k}~/{v.pattern}/" if isinstance(v, re.Pattern) else f"{k}={v!r}"
            for k, v in args.items()
        )
        + "}"
    )


def compute_metrics(run: ScenarioRun, cost_per_minute: Optional[float] = None) -> Metrics:
    trace, scenario, caps = run.trace, run.scenario, run.capabilities
    m = Metrics()
    m.ttfa_ms = time_to_first_audio(trace)
    m.turn_latency_ms = turn_latencies(trace)
    m.barge_ins, m.barge_ins_handled, m.barge_in_ms = barge_ins(trace)

    m.tool_calls = [
        (e.data["name"], e.data.get("args") or {}) for e in trace.select("in", "tool_call")
    ]
    m.tool_failures = tool_call_failures(scenario, m.tool_calls)

    # Providers stream transcripts as fragments, so join without separators.
    m.transcript = "".join(str(e.data) for e in trace.select("in", "text"))
    m.transcript_failures = [
        p for p in scenario.transcript_patterns if not re.search(p, m.transcript)
    ]

    resumed = trace.select("in", "session_resumed")
    m.reconnects = len(resumed)
    m.reconnects_recovered = sum(
        1 for e in resumed if trace.first("in", "turn_complete", e.i) is not None
    )

    m.audio_in_s = round(
        sum(e.data for e in trace.select("out", "audio")) / 2 / caps.input_sample_rate, 2
    )
    m.audio_out_s = round(
        sum(e.data for e in trace.select("in", "audio")) / 2 / caps.output_sample_rate, 2
    )
    if cost_per_minute is not None:
        m.cost_usd = round((m.audio_in_s + m.audio_out_s) / 60 * cost_per_minute, 4)
    return m
