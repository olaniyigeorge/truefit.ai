import pytest

from soro import create_live_adapter
from soro.adapters import factory
from soro.adapters.fallback import FallbackLiveAdapter
from soro.testing import FakeLiveAdapter

pytestmark = pytest.mark.unit


@pytest.fixture
def made(monkeypatch):
    """Replace the real adapters with fakes and record how they were built."""
    calls: list[tuple[str, dict]] = []

    def fake_make(provider, **opts):
        if provider not in ("gemini", "openai"):
            raise ValueError(f"Unknown provider: {provider!r}")
        calls.append((provider, opts))
        return FakeLiveAdapter()

    monkeypatch.setattr(factory, "_make_adapter", fake_make)
    return calls


def test_defaults_to_gemini_without_a_fallback(made):
    assert isinstance(create_live_adapter(), FakeLiveAdapter)
    assert [p for p, _ in made] == ["gemini"]


def test_fallback_wraps_both_in_order(made):
    adapter = create_live_adapter("openai", "gemini")
    assert isinstance(adapter, FallbackLiveAdapter)
    assert [p for p, _ in made] == ["openai", "gemini"]


@pytest.mark.parametrize("primary,fallback", [("", ""), (None, None), ("  ", " ")])
def test_blank_values_use_the_defaults(made, primary, fallback):
    assert isinstance(create_live_adapter(primary, fallback), FakeLiveAdapter)
    assert [p for p, _ in made] == ["gemini"]


def test_names_are_case_and_whitespace_insensitive(made):
    create_live_adapter(" OpenAI ", " NONE ")
    assert [p for p, _ in made] == ["openai"]


def test_credentials_and_models_reach_the_adapters(made):
    create_live_adapter(
        "gemini", "openai",
        gemini_api_key="g", gemini_model="gm", gemini_voice="Puck",
        openai_api_key="o", openai_model="om", openai_voice="marin",
    )
    opts = made[0][1]
    assert (opts["gemini_api_key"], opts["gemini_model"], opts["gemini_voice"]) == ("g", "gm", "Puck")
    assert (opts["openai_api_key"], opts["openai_model"], opts["openai_voice"]) == ("o", "om", "marin")


def test_same_primary_and_fallback_rejected(made):
    with pytest.raises(ValueError, match="cannot be the same"):
        create_live_adapter("gemini", "gemini")
    assert made == []  # rejected before anything was built


def test_unknown_provider_rejected(made):
    with pytest.raises(ValueError, match="Unknown provider"):
        create_live_adapter("nope")


def test_real_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_live_adapter("nope")


def test_real_factory_builds_real_adapters_from_arguments(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from soro.adapters.gemini import GeminiLiveAdapter
    from soro.adapters.openai import OpenAIRealtimeAdapter

    assert isinstance(create_live_adapter("gemini", gemini_api_key="k"), GeminiLiveAdapter)
    assert isinstance(create_live_adapter("openai", openai_api_key="k"), OpenAIRealtimeAdapter)
    both = create_live_adapter("gemini", "openai", gemini_api_key="g", openai_api_key="o")
    assert isinstance(both, FallbackLiveAdapter)


def test_missing_key_for_a_chosen_provider_fails_loudly(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        create_live_adapter("openai")
