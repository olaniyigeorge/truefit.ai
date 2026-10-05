"""
python -m soro.evals: compare turn detectors and providers from the terminal.

    python -m soro.evals turns                         # noisy-room end-of-turn, energy vs silero
    python -m soro.evals scenarios                     # every scenario on the scripted baseline
    python -m soro.evals scenarios -p scripted,gemini  # add a real provider (needs its key)
    python -m soro.evals scenarios --list
    python -m soro.evals all

Real providers read their usual environment variables (GEMINI_API_KEY,
OPENAI_API_KEY); "composed" needs a local LLM server and the speech models. A
provider that cannot be built is reported as skipped. `scenarios` exits 1 when
any run fails, so it can gate CI; `turns` is a side-by-side comparison and only
fails when no detector could run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional

from soro.evals.report import format_scorecards, run_suite
from soro.evals.scenario import ScenarioRunner, get_scenarios
from soro.evals.scripted_adapter import ScriptedAdapter
from soro.evals.turn_detection import compare_detectors, format_report

ACOUSTIC_DETECTORS = {"silero"}  # classify real speech, so synthetic "speech" is not theirs to find


def _turns(detectors: list[str]) -> bool:
    from soro.audio.turn import create_turn_detector

    factories = {}
    for name in detectors:
        try:
            create_turn_detector(name)  # fail here, once, with the install hint
        except ImportError as exc:
            print(f"skipping {name}: {exc}\n")
            continue
        factories[name] = lambda n=name: create_turn_detector(n)
    if not factories:
        return False
    results = compare_detectors(factories, acoustic_detectors=ACOUSTIC_DETECTORS & set(factories))
    print(format_report(results))
    # A comparison, not a gate: the energy detector's known weakness (a fan that
    # switches on mid-call) is exactly what this table is meant to show.
    return True


def _provider_factory(name: str):
    if name == "scripted":
        return lambda scenario: ScriptedAdapter(scenario.script)

    def build(scenario):
        from soro.adapters.factory import create_live_adapter

        return create_live_adapter(name, "none")

    return build


def _scenarios(providers: list[str], names: Optional[list[str]], costs: dict[str, float],
               turn_timeout: float, session_timeout: float = 120.0) -> bool:
    scenarios = get_scenarios(names)
    factories = {p: _provider_factory(p) for p in providers}
    live = {p for p in providers if p != "scripted"}
    runner = ScenarioRunner(turn_timeout_s=turn_timeout, session_timeout_s=session_timeout)
    cards = asyncio.run(run_suite(factories, scenarios, runner=runner, cost_per_minute=costs, live=live))
    print(format_scorecards(cards))
    return all(c.passed for c in cards if not c.skipped)


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _costs(values: list[str]) -> dict[str, float]:
    out = {}
    for item in values:
        provider, _, rate = item.partition("=")
        out[provider] = float(rate)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m soro.evals", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    turns = sub.add_parser("turns", help="noisy-room turn-detection comparison")
    turns.add_argument("-d", "--detectors", type=_csv, default=["energy", "silero"],
                       help="comma-separated detector names (default: energy,silero)")

    scen = sub.add_parser("scenarios", help="scenario evals per provider")
    scen.add_argument("-p", "--providers", type=_csv, default=["scripted"],
                      help="comma-separated: scripted, gemini, openai, composed (default: scripted)")
    scen.add_argument("-s", "--scenarios", type=_csv, default=None, help="comma-separated scenario names")
    scen.add_argument("--cost", action="append", default=[], metavar="PROVIDER=USD_PER_MIN",
                      help="audio price per minute, for a cost estimate (repeatable)")
    scen.add_argument("--turn-timeout", type=float, default=20.0, help="seconds to wait for each reply")
    scen.add_argument("--session-timeout", type=float, default=120.0,
                      help="seconds a whole scenario may take (raise it for a local model on CPU)")
    scen.add_argument("--list", action="store_true", help="list the scenarios and exit")

    sub.add_parser("all", help="turn detection, then every scenario on the scripted baseline")

    args = parser.parse_args(argv)
    # The runtime logs provider events (a resumed session) at WARNING; in a report
    # they are expected and already scored, so keep the table readable.
    logging.getLogger("soro").setLevel(logging.ERROR)
    if args.command == "turns":
        return 0 if _turns(args.detectors) else 1
    if args.command == "scenarios":
        if args.list:
            for s in get_scenarios():
                print(f"{s.name:<17}{'live' if s.live else 'scripted only':<15}{s.description}")
            return 0
        return 0 if _scenarios(args.providers, args.scenarios, _costs(args.cost), args.turn_timeout,
                              args.session_timeout) else 1
    ok_turns = _turns(["energy", "silero"])
    print()
    ok_scen = _scenarios(["scripted"], None, {}, 20.0)
    return 0 if ok_turns and ok_scen else 1


if __name__ == "__main__":
    sys.exit(main())
