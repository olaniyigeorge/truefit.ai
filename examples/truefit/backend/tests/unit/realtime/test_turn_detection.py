"""The app's turn detector choice: AppConfig in, a Soro detector out."""

import builtins

import pytest
from soro.audio import EnergyTurnDetector

from src.truefit_infra.config import AppConfig
from src.truefit_infra.realtime.turn_detection import create_turn_detector

pytestmark = pytest.mark.unit


def test_default_is_silero(monkeypatch):
    pytest.importorskip("onnxruntime")
    from soro.audio import SileroTurnDetector

    monkeypatch.setattr(AppConfig, "VOICE_TURN_DETECTOR", "", raising=False)
    assert isinstance(create_turn_detector(), SileroTurnDetector)


def test_energy_can_be_selected(monkeypatch):
    monkeypatch.setattr(AppConfig, "VOICE_TURN_DETECTOR", " Energy ", raising=False)
    assert isinstance(create_turn_detector(), EnergyTurnDetector)


def test_falls_back_to_energy_without_onnxruntime(monkeypatch):
    monkeypatch.setattr(AppConfig, "VOICE_TURN_DETECTOR", "silero", raising=False)
    real_import = builtins.__import__

    def no_onnxruntime(name, *args, **kwargs):
        if name == "onnxruntime":
            raise ImportError("No module named 'onnxruntime'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_onnxruntime)
    assert isinstance(create_turn_detector(), EnergyTurnDetector)


def test_unknown_detector_is_an_error(monkeypatch):
    monkeypatch.setattr(AppConfig, "VOICE_TURN_DETECTOR", "magic", raising=False)
    with pytest.raises(ValueError):
        create_turn_detector()
