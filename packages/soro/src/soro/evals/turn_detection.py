"""
Turn-detection eval: the noisy-room scenario.

Run a detector over a fixture of 20ms frames, collect its start/end events, and
score the three things that matter for end-of-turn:

- false_starts / false_ends: boundaries reported during stretches with no speech.
  This is the fan-noise bug made measurable. The old hand-rolled detector held a
  turn open on steady noise; a good detector reports zero here.
- detected_turn: for a case that contains speech, did exactly one turn start and
  end? A miss (no turn) or a split (several) both fail.
- end_latency_ms: for a detected turn, how long after the speaker actually stopped
  did the "end" fire. Lower is snappier; too low clips the speaker between words.

compare_detectors() runs several named detectors over the same cases so the energy
and neural detectors sit side by side on identical audio.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from soro.audio.turn import TurnDetector
from soro.evals.audio_fixtures import FRAME_MS, fan, mix, quiet, speech_frames

DetectorFactory = Callable[[], TurnDetector]


@dataclass(frozen=True)
class TurnCase:
    """
    A fixture plus what we expect of it.

    frames: 20ms PCM frames fed in order.
    speech_present: whether the case contains a real turn to detect.
    speech_end_s: when the speech actually stops, used to measure end latency.
    acoustic: True means the "speech" is only an energy envelope, not real
        speech acoustics, so an energy detector should find it but a neural
        detector is not expected to. Keeps the comparison honest.
    """

    name: str
    frames: list[bytes]
    speech_present: bool
    speech_end_s: Optional[float] = None
    acoustic: bool = False
    description: str = ""


@dataclass
class TurnCaseResult:
    case: str
    events: list[tuple[float, str]] = field(default_factory=list)
    false_starts: int = 0
    false_ends: int = 0
    detected_turn: bool = False
    end_latency_ms: Optional[float] = None
    passed: bool = False


def score_case(
    factory: DetectorFactory, case: TurnCase, acoustic_ok: bool = True
) -> TurnCaseResult:
    """
    Feed the case through a fresh detector and score it. acoustic_ok=False marks
    acoustic cases as not-expected-to-pass (used for detectors that classify
    speech rather than energy), so a correct rejection is not counted as a miss.
    """
    detector = factory()
    events: list[tuple[float, str]] = []
    for i, frame in enumerate(case.frames):
        ev = detector.process(frame)
        if ev is not None:
            events.append((round(i * FRAME_MS / 1000, 3), ev.kind))

    result = TurnCaseResult(case=case.name, events=events)
    starts = [e for e in events if e[1] == "start"]
    ends = [e for e in events if e[1] == "end"]

    if not case.speech_present:
        result.false_starts = len(starts)
        result.false_ends = len(ends)
        result.passed = len(events) == 0
        return result

    # A clean turn is exactly one start then one end.
    result.detected_turn = [k for _, k in events] == ["start", "end"]
    if len(starts) > 1 or len(ends) > 1:
        result.false_starts = max(0, len(starts) - 1)
        result.false_ends = max(0, len(ends) - 1)
    if result.detected_turn and case.speech_end_s is not None:
        result.end_latency_ms = max(0.0, (ends[0][0] - case.speech_end_s) * 1000)

    expected = True if (acoustic_ok or not case.acoustic) else False
    result.passed = result.detected_turn if expected else (len(events) == 0 or result.detected_turn)
    return result


def _cases(seed: int = 1234) -> list[TurnCase]:
    rng = random.Random(seed)
    out: list[TurnCase] = []

    out.append(
        TurnCase(
            "quiet_room",
            quiet(3, rng),
            speech_present=False,
            description="A quiet room must never report a turn.",
        )
    )

    out.append(
        TurnCase(
            "steady_fan",
            fan(20, rng),
            speech_present=False,
            description="Steady fan noise from the start: the classic false-turn trap.",
        )
    )

    frames = quiet(2, rng) + fan(12, rng)
    out.append(
        TurnCase(
            "fan_switches_on",
            frames,
            speech_present=False,
            description="A fan that starts mid-call must be learned, not held as a turn.",
        )
    )

    frames = quiet(1, rng) + speech_frames(2, rng) + quiet(2, rng)
    out.append(
        TurnCase(
            "speech_in_quiet",
            frames,
            speech_present=True,
            speech_end_s=3.0,
            acoustic=True,
            description="One turn in a quiet room.",
        )
    )

    speech = mix(speech_frames(2, rng, rms=8000), fan(2, rng))
    frames = fan(2, rng) + speech + fan(3, rng)
    out.append(
        TurnCase(
            "speech_over_fan",
            frames,
            speech_present=True,
            speech_end_s=4.0,
            acoustic=True,
            description="A turn spoken over fan noise, then noise alone.",
        )
    )

    return out


NOISY_ROOM_CASES: list[TurnCase] = _cases()


def compare_detectors(
    factories: dict[str, DetectorFactory],
    cases: Optional[list[TurnCase]] = None,
    acoustic_detectors: Optional[set[str]] = None,
) -> dict[str, list[TurnCaseResult]]:
    """
    Run every named detector over the same cases. acoustic_detectors names the
    detectors that classify real speech (so they are not penalised for rejecting
    the synthetic acoustic cases).
    """
    cases = cases or NOISY_ROOM_CASES
    acoustic_detectors = acoustic_detectors or set()
    return {
        name: [score_case(factory, c, acoustic_ok=name not in acoustic_detectors) for c in cases]
        for name, factory in factories.items()
    }


def format_report(results: dict[str, list[TurnCaseResult]]) -> str:
    """A plain-text table, one block per detector, readable in a terminal or a log."""
    lines: list[str] = []
    for name, rows in results.items():
        passed = sum(1 for r in rows if r.passed)
        lines.append(f"== {name}  ({passed}/{len(rows)} cases passed) ==")
        lines.append(
            f"{'case':<18}{'pass':<6}{'false_start':<13}{'false_end':<11}{'turn':<6}{'end_latency':<12}"
        )
        for r in rows:
            latency = "-" if r.end_latency_ms is None else f"{r.end_latency_ms:.0f}ms"
            lines.append(
                f"{r.case:<18}{('yes' if r.passed else 'NO'):<6}"
                f"{r.false_starts:<13}{r.false_ends:<11}"
                f"{('yes' if r.detected_turn else '-'):<6}{latency:<12}"
            )
        lines.append("")
    return "\n".join(lines)
