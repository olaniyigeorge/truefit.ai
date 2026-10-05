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
        COMPOSED_LLM_BASE_URL=None,
        COMPOSED_LLM_MODEL=None,
        COMPOSED_STT_MODEL=None,
        COMPOSED_TTS_VOICE=None,
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


def test_composed_settings_reach_the_local_pipeline(monkeypatch, tmp_path):
    pytest.importorskip("faster_whisper")
    pytest.importorskip("piper")
    from soro.adapters.composed import ComposedLiveAdapter

    voice = tmp_path / "voice.onnx"
    voice.write_bytes(b"")  # loaded lazily, so an empty file is enough here
    (tmp_path / "voice.onnx.json").write_text('{"audio": {"sample_rate": 22050}}')
    _configure(
        monkeypatch,
        LLM_PRIMARY_PROVIDER="composed",
        COMPOSED_LLM_BASE_URL="http://127.0.0.1:8080/v1",
        COMPOSED_LLM_MODEL="qwen2.5:7b",
        COMPOSED_STT_MODEL="small.en",
        COMPOSED_TTS_VOICE=str(voice),
    )
    adapter = create_live_adapter()
    assert isinstance(adapter, ComposedLiveAdapter)
    assert adapter.llm.base_url == "http://127.0.0.1:8080/v1"
    assert adapter.llm.model == "qwen2.5:7b"
    assert adapter.stt.model_name == "small.en"
    assert adapter.capabilities.output_sample_rate == 22050
    assert adapter.capabilities.input_sample_rate == 16_000  # what the audio bridge delivers
