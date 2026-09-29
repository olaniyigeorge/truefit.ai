import pytest

from src.truefit_infra.config import AppConfig
from src.truefit_infra.llm import factory
from src.truefit_infra.llm.fallback_adapter import FallbackLiveAdapter
from tests.unit.llm.fakes import FakeLiveAdapter

pytestmark = pytest.mark.unit


@pytest.fixture
def providers(monkeypatch):
    """Replace real adapters with fakes so no SDK or API key is needed."""
    made: list[str] = []

    def fake_make(name: str):
        if name not in ("gemini", "openai"):
            raise ValueError(f"Unknown LLM provider: {name!r}")
        made.append(name)
        return FakeLiveAdapter()

    monkeypatch.setattr(factory, "_make_adapter", fake_make)
    return made


def _configure(monkeypatch, primary, fallback):
    monkeypatch.setattr(AppConfig, "LLM_PRIMARY_PROVIDER", primary, raising=False)
    monkeypatch.setattr(AppConfig, "LLM_FALLBACK_PROVIDER", fallback, raising=False)


def test_no_fallback_returns_primary_directly(monkeypatch, providers):
    _configure(monkeypatch, "gemini", "none")
    assert isinstance(factory.create_live_adapter(), FakeLiveAdapter)
    assert providers == ["gemini"]


def test_fallback_wraps_both(monkeypatch, providers):
    _configure(monkeypatch, "gemini", "openai")
    assert isinstance(factory.create_live_adapter(), FallbackLiveAdapter)
    assert providers == ["gemini", "openai"]


def test_blank_env_values_use_defaults(monkeypatch, providers):
    _configure(monkeypatch, "", "")
    assert isinstance(factory.create_live_adapter(), FakeLiveAdapter)
    assert providers == ["gemini"]


def test_names_are_case_and_whitespace_insensitive(monkeypatch, providers):
    _configure(monkeypatch, " OpenAI ", " NONE ")
    factory.create_live_adapter()
    assert providers == ["openai"]


def test_same_primary_and_fallback_rejected(monkeypatch, providers):
    _configure(monkeypatch, "gemini", "gemini")
    with pytest.raises(ValueError, match="cannot be the same"):
        factory.create_live_adapter()


def test_unknown_provider_rejected(monkeypatch, providers):
    _configure(monkeypatch, "claude", "none")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        factory.create_live_adapter()


def test_real_make_adapter_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        factory._make_adapter("nope")


def test_openai_without_key_fails_loudly(monkeypatch):
    monkeypatch.setattr(AppConfig, "OPENAI_API_KEY", None, raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        factory._make_adapter("openai")


def test_default_config_is_gemini_only():
    """Guards the bug where a default openai fallback broke Gemini-only setups."""
    from src.truefit_infra.config import GlobalConfig

    assert GlobalConfig.model_fields["LLM_FALLBACK_PROVIDER"].default == "none"
