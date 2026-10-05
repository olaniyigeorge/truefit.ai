"""
Scorecards: one row per (provider, scenario), and a plain-text table of them.

A Scorecard is the flattened, comparable view of a run. `passed` is strict: the
run finished, every expected tool call happened correctly, the transcript
matched, every barge-in was handled within budget and every reconnect recovered.
Latency is reported, not judged, because the right budget depends on the product.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from soro.evals.metrics import Metrics, compute_metrics
from soro.evals.scenario import Scenario, ScenarioRun, ScenarioRunner
from soro.ports import LiveSessionPort


@dataclass
class Scorecard:
    provider: str
    scenario: str
    passed: bool
    ttfa_ms: Optional[float] = None
    turn_latency_ms: Optional[float] = None
    turn_latency_max_ms: Optional[float] = None
    barge_in: str = "-"
    barge_in_ms: Optional[float] = None
    tool_calls_ok: bool = True
    transcript_ok: bool = True
    reconnects: str = "-"
    audio_in_s: float = 0.0
    audio_out_s: float = 0.0
    cost_usd: Optional[float] = None
    failures: list[str] = field(default_factory=list)
    skipped: Optional[str] = None


def scorecard(run: ScenarioRun, cost_per_minute: Optional[float] = None) -> Scorecard:
    m: Metrics = compute_metrics(run, cost_per_minute)
    failures = list(m.tool_failures) + [f"transcript did not match /{p}/" for p in m.transcript_failures]
    if run.error:
        failures.insert(0, run.error)
    if run.timeouts:
        failures.append(f"{run.timeouts} reply timeout(s)")
    if m.barge_ins_handled < m.barge_ins:
        failures.append(f"barge-in handled {m.barge_ins_handled}/{m.barge_ins}")
    if m.reconnects_recovered < m.reconnects:
        failures.append(f"recovered {m.reconnects_recovered}/{m.reconnects} reconnects")
    return Scorecard(
        provider=run.provider,
        scenario=run.scenario.name,
        passed=not failures,
        ttfa_ms=m.ttfa_ms,
        turn_latency_ms=None if m.mean_turn_latency_ms is None else round(m.mean_turn_latency_ms, 1),
        turn_latency_max_ms=max(m.turn_latency_ms) if m.turn_latency_ms else None,
        barge_in=f"{m.barge_ins_handled}/{m.barge_ins}" if m.barge_ins else "-",
        barge_in_ms=max(m.barge_in_ms) if m.barge_in_ms else None,
        tool_calls_ok=not m.tool_failures,
        transcript_ok=not m.transcript_failures,
        reconnects=f"{m.reconnects_recovered}/{m.reconnects}" if m.reconnects else "-",
        audio_in_s=m.audio_in_s,
        audio_out_s=m.audio_out_s,
        cost_usd=m.cost_usd,
        failures=failures,
    )


def skipped(provider: str, scenario: str, reason: str) -> Scorecard:
    return Scorecard(provider=provider, scenario=scenario, passed=False, skipped=reason)


def _num(value: Optional[float], unit: str = "ms") -> str:
    return "-" if value is None else f"{value:.0f}{unit}"


def format_scorecards(cards: list[Scorecard]) -> str:
    header = (f"{'provider':<14}{'scenario':<17}{'pass':<6}{'ttfa':<8}{'turn':<8}{'turn_max':<10}"
              f"{'barge_in':<10}{'tools':<7}{'transcript':<12}{'reconnect':<11}{'audio in/out':<14}{'cost':<8}")
    lines = [header, "-" * len(header)]
    notes: list[str] = []
    for c in cards:
        if c.skipped:
            lines.append(f"{c.provider:<14}{c.scenario:<17}{'skip':<6}{c.skipped}")
            continue
        cost = "-" if c.cost_usd is None else f"${c.cost_usd:.3f}"
        barge = c.barge_in if c.barge_in_ms is None else f"{c.barge_in} {c.barge_in_ms:.0f}ms"
        lines.append(
            f"{c.provider:<14}{c.scenario:<17}{('yes' if c.passed else 'NO'):<6}"
            f"{_num(c.ttfa_ms):<8}{_num(c.turn_latency_ms):<8}{_num(c.turn_latency_max_ms):<10}"
            f"{barge:<10}{('ok' if c.tool_calls_ok else 'FAIL'):<7}{('ok' if c.transcript_ok else 'FAIL'):<12}"
            f"{c.reconnects:<11}{f'{c.audio_in_s:.1f}s/{c.audio_out_s:.1f}s':<14}{cost:<8}"
        )
        notes.extend(f"  {c.provider}/{c.scenario}: {f}" for f in c.failures)
    passed = sum(1 for c in cards if c.passed)
    ran = sum(1 for c in cards if not c.skipped)
    lines.append("")
    lines.append(f"{passed}/{ran} runs passed")
    if notes:
        lines.append("Failures:")
        lines.extend(notes)
    return "\n".join(lines)


AdapterFactory = Callable[[Scenario], LiveSessionPort]


async def run_suite(
    providers: dict[str, AdapterFactory],
    scenarios: Sequence[Scenario],
    *,
    runner: Optional[ScenarioRunner] = None,
    cost_per_minute: Optional[dict[str, float]] = None,
    live: Optional[set[str]] = None,
) -> list[Scorecard]:
    """
    Run every scenario on every provider, one session at a time (parallel runs
    would make the latency numbers measure contention). `live` names the real
    providers: they skip scenarios marked live=False. A factory that raises (a
    missing key or extra) becomes a skipped row, not a crash, so one unavailable
    provider does not hide the others' results.
    """
    runner = runner or ScenarioRunner()
    live = live or set()
    rates = cost_per_minute or {}
    cards: list[Scorecard] = []
    for provider, make in providers.items():
        for scenario in scenarios:
            if provider in live and not scenario.live:
                cards.append(skipped(provider, scenario.name, "needs scripted audio"))
                continue
            try:
                adapter = make(scenario)
            except Exception as exc:
                cards.append(skipped(provider, scenario.name, f"unavailable: {exc}"))
                continue
            run = await runner.run(scenario, adapter, provider)
            cards.append(scorecard(run, rates.get(provider)))
    return cards
