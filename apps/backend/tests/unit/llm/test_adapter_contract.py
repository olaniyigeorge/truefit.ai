"""
Contract every LiveSessionPort adapter must honour. Runs against the fake, the
fallback wrapper and the real Gemini and OpenAI adapters (no network: only
static behaviour that works without an open session).
"""

import inspect

import pytest

from src.truefit_core.application.ports import (
    LIVE_EVENT_TYPES,
    AdapterCapabilities,
    LiveSessionPort,
)
from src.truefit_core.application.tools import ToolSpec
from src.truefit_core.common.exceptions import CapabilityNotSupported
from src.truefit_infra.llm.fallback_adapter import FallbackLiveAdapter
from tests.unit.llm.fakes import FakeLiveAdapter

pytestmark = pytest.mark.unit


def _gemini():
    from src.truefit_infra.llm.gemini_live import GeminiLiveAdapter

    return GeminiLiveAdapter(api_key="test-key")


def _openai():
    from src.truefit_infra.llm.openai_realtime import OpenAIRealtimeAdapter

    return OpenAIRealtimeAdapter(api_key="test-key")


ADAPTERS = {
    "fake": lambda: FakeLiveAdapter(),
    "fallback": lambda: FallbackLiveAdapter(primary=FakeLiveAdapter(), fallback=FakeLiveAdapter()),
    "gemini": _gemini,
    "openai": _openai,
}


@pytest.fixture(params=list(ADAPTERS))
def adapter(request) -> LiveSessionPort:
    return ADAPTERS[request.param]()


def test_is_a_live_session_port(adapter):
    assert isinstance(adapter, LiveSessionPort)


def test_capabilities_are_declared_and_sane(adapter):
    caps = adapter.capabilities
    assert isinstance(caps, AdapterCapabilities)
    assert caps.input_sample_rate in (8_000, 16_000, 24_000, 44_100, 48_000)
    assert caps.output_sample_rate in (8_000, 16_000, 24_000, 44_100, 48_000)
    assert isinstance(caps.supports_images, bool) and isinstance(caps.native_vad, bool)


def test_optional_turn_and_stream_methods_are_coroutines(adapter):
    for name in ("send_activity_start", "send_activity_end", "send_audio_stream_end"):
        assert inspect.iscoroutinefunction(getattr(adapter, name)), name


async def test_send_image_matches_supports_images(adapter):
    if adapter.capabilities.supports_images:
        pytest.skip("image-capable adapters need an open session to accept frames")
    if isinstance(adapter, FallbackLiveAdapter):
        pytest.skip("the wrapper needs an open session; covered in test_fallback_adapter")
    with pytest.raises(CapabilityNotSupported):
        await adapter.send_image(b"\xff\xd8", "camera")


def test_open_session_accepts_toolspecs_and_returns_context_manager(adapter):
    ctx = adapter.open_session("prompt", tools=[ToolSpec(name="ping")])
    assert hasattr(ctx, "__aenter__") and hasattr(ctx, "__aexit__")


@pytest.mark.parametrize("make", [_gemini, _openai], ids=["gemini", "openai"])
def test_real_adapters_reject_duplicate_tool_names_before_connecting(make):
    with pytest.raises(ValueError, match="Duplicate"):
        make().open_session("p", tools=[ToolSpec(name="a"), ToolSpec(name="a")])


def test_event_vocabulary_is_neutral():
    assert "go_away" not in LIVE_EVENT_TYPES
    assert "session_ending" in LIVE_EVENT_TYPES


# ── Provider wire-format translation


def test_gemini_translation_groups_declarations():
    from src.truefit_infra.llm.gemini_live import _to_gemini_tools

    spec = ToolSpec(name="a", description="d", parameters={"type": "object", "properties": {}})
    assert _to_gemini_tools([spec]) == [
        {"function_declarations": [{"name": "a", "description": "d", "parameters": spec.parameters}]}
    ]
    assert _to_gemini_tools([]) is None


def test_openai_translation_uses_function_tools():
    from src.truefit_infra.llm.openai_realtime import _to_openai_tools

    spec = ToolSpec(name="a", description="d")
    assert _to_openai_tools([spec]) == [
        {"type": "function", "name": "a", "description": "d", "parameters": spec.parameters}
    ]


def test_openai_can_now_translate_the_interview_tools():
    """Regression: the Gemini group shape used to be passed to OpenAI untouched."""
    from src.truefit_core.agents.interviewer.tools import INTERVIEW_TOOLS
    from src.truefit_core.application.tools import normalize_tools
    from src.truefit_infra.llm.openai_realtime import _to_openai_tools

    tools = _to_openai_tools(normalize_tools(INTERVIEW_TOOLS))
    assert tools and all(t["type"] == "function" and t["name"] and "function_declarations" not in t for t in tools)


def test_provider_capabilities_reflect_how_they_are_run():
    g, o = _gemini().capabilities, _openai().capabilities
    assert (g.input_sample_rate, g.output_sample_rate) == (16_000, 24_000)
    assert (o.input_sample_rate, o.output_sample_rate) == (16_000, 24_000)
    assert g.supports_images is True and o.supports_images is False
