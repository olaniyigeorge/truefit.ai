"""
Soro evals: measure what "model-agnostic" is supposed to deliver.

Two kinds of eval, both runnable with no network or API key:

- Turn detection: run audio fixtures through any TurnDetector and score false
  triggers, true turns and end-of-turn latency. This is the "noisy-room"
  scenario, and how the energy and neural detectors are compared on the same audio.
- Scenarios: drive a VoiceAgentRuntime through a scripted caller on any
  LiveSessionPort and score time to first audio, turn latency, barge-in,
  tool-call correctness and reconnect recovery. ScriptedAdapter is the cheap,
  deterministic baseline; real providers are opt-in and need their keys.

From the terminal: python -m soro.evals --help
"""

from __future__ import annotations

from soro.evals.metrics import Metrics, compute_metrics
from soro.evals.report import Scorecard, format_scorecards, run_suite, scorecard
from soro.evals.scenario import (
    BUILTIN_SCENARIOS,
    CallerTurn,
    ExpectedCall,
    Scenario,
    ScenarioRun,
    ScenarioRunner,
    get_scenarios,
)
from soro.evals.scripted_adapter import ScriptedAdapter, speech
from soro.evals.trace import Trace, TraceEvent, TracingAdapter
from soro.evals.turn_detection import (
    NOISY_ROOM_CASES,
    TurnCase,
    TurnCaseResult,
    compare_detectors,
    format_report,
    score_case,
)

__all__ = [
    "BUILTIN_SCENARIOS",
    "CallerTurn",
    "ExpectedCall",
    "Metrics",
    "NOISY_ROOM_CASES",
    "Scenario",
    "ScenarioRun",
    "ScenarioRunner",
    "Scorecard",
    "ScriptedAdapter",
    "Trace",
    "TraceEvent",
    "TracingAdapter",
    "TurnCase",
    "TurnCaseResult",
    "compare_detectors",
    "compute_metrics",
    "format_report",
    "format_scorecards",
    "get_scenarios",
    "run_suite",
    "score_case",
    "scorecard",
    "speech",
]
