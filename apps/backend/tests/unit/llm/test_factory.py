"""The app's adapter factory: AppConfig in, a Soro adapter out."""

import pytest
from soro.adapters.fallback import FallbackLiveAdapter
from soro.adapters.gemini import GeminiLiveAdapter
from soro.adapters.openai import OpenAIRealtimeAdapter

from src.truefit_infra.config import AppConfig, GlobalConfig
from src.truefit_infra.llm.factory import create_live_adapter

pytestmark = pytest.mark.unit


def _configure(monkeypatch, **values):
    defaults = dict(
        LLM_PRIMARY_PROVIDER="gemini",
        LLM_FALLBACK_PROVIDER="none",
        GEMINI_API_KEY="g-key",
        GEMINI_LIVE_MODEL=None,
        OPENAI_API_KEY="o-key",
        OPENAI_REALTIME_MODEL=None,
    )
    for name, value in {**defaults, **values}.items():
        monkeypatch.setattr(AppConfig, name, value, raising=False)


def test_gemini_only(monkeypatch):
    _configure(monkeypatch)
    assert isinstance(create_live_adapter(), GeminiLiveAdapter)


def test_openai_primary_with_gemini_fallback(monkeypatch):
    _configure(monkeypatch, LLM_PRIMARY_PROVIDER="openai", LLM_FALLBACK_PROVIDER="gemini")
    assert isinstance(create_live_adapter(), FallbackLiveAdapter)


def test_blank_settings_use_the_defaults(monkeypatch):
    """Regression: a blank LLM_PRIMARY_PROVIDER in .env used to raise 'Unknown provider'."""
    _configure(monkeypatch, LLM_PRIMARY_PROVIDER="", LLM_FALLBACK_PROVIDER="")
    assert isinstance(create_live_adapter(), GeminiLiveAdapter)


def test_model_setting_reaches_the_adapter(monkeypatch):
    _configure(monkeypatch, GEMINI_LIVE_MODEL="my-model")
    assert create_live_adapter()._model == "my-model"


def test_a_missing_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _configure(monkeypatch, LLM_PRIMARY_PROVIDER="openai", OPENAI_API_KEY=None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        create_live_adapter()


def test_default_config_is_gemini_only():
    """Guards the bug where a default openai fallback broke Gemini-only setups."""
    assert GlobalConfig.model_fields["LLM_FALLBACK_PROVIDER"].default == "none"
