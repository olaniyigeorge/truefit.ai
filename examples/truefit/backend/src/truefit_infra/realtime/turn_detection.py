"""
Builds the turn detector the AudioBridge uses to decide when the candidate
starts and stops talking.

Setting read from AppConfig:
  VOICE_TURN_DETECTOR   "silero" | "energy"   (blank means silero)

Silero is the default because the energy detector false-triggers when steady
noise such as a fan starts mid-call (see `python -m soro.evals turns`). If
soro[vad] is not installed, the app logs a warning and falls back to the energy
detector rather than failing the interview.
"""

from __future__ import annotations

from soro.audio import TurnDetector, create_turn_detector as soro_create_turn_detector

from src.truefit_core.common.utils import logger
from src.truefit_infra.config import AppConfig

DEFAULT_TURN_DETECTOR = "silero"


def create_turn_detector() -> TurnDetector:
    kind = (getattr(AppConfig, "VOICE_TURN_DETECTOR", None) or DEFAULT_TURN_DETECTOR).strip().lower()
    try:
        return soro_create_turn_detector(kind)
    except ImportError as exc:
        if kind != "energy":
            logger.warning(f"Turn detector {kind!r} unavailable ({exc}); using the energy detector")
            return soro_create_turn_detector("energy")
        raise
