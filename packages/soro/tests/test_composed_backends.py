"""
The composed adapter's local backends. The LLM client runs against an
httpx.MockTransport streaming server-sent events, so it is fully exercised with
no server. faster-whisper and Piper need their packages and model files, so
those tests skip unless the dependency and SORO_TEST_* model paths are present.
"""

from __future__ import annotations

import json
import os

import pytest

from soro.adapters.composed import TextDelta, ToolCallRequest
from soro.adapters.composed.piper_tts import voice_sample_rate
from soro.tools import ToolSpec

pytestmark = pytest.mark.unit


def _sse(*events) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def _delta(**delta):
    return {"choices": [{"index": 0, "delta": delta}]}


async def _drain(llm, messages=None, tools=()):
    return [c async for c in llm.stream(messages or [{"role": "user", "content": "hi"}], list(tools))]


async def test_llm_streams_text_and_assembles_fragmented_tool_calls():
    httpx = pytest.importorskip("httpx")
    from soro.adapters.composed.openai_compat_llm import OpenAICompatibleLLM

    seen = {}

    def server(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        body = _sse(
            _delta(content="Let me "),
            _delta(content="check."),
            _delta(tool_calls=[{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ""}}]),
            _delta(tool_calls=[{"index": 0, "function": {"arguments": '{"city": '}}]),
            _delta(tool_calls=[{"index": 0, "function": {"arguments": '"Lagos"}'}}]),
            _delta(tool_calls=[{"index": 1, "id": "call_2", "function": {"name": "noop", "arguments": "{}"}}]),
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    llm = OpenAICompatibleLLM(base_url="http://local/v1/", model="qwen2.5", transport=httpx.MockTransport(server))
    tool = ToolSpec(name="get_weather", description="Weather.")
    chunks = await _drain(llm, tools=[tool])
    await llm.aclose()

    assert chunks == [
        TextDelta("Let me "), TextDelta("check."),
        ToolCallRequest("call_1", "get_weather", {"city": "Lagos"}),
        ToolCallRequest("call_2", "noop", {}),
    ]
    assert seen["url"] == "http://local/v1/chat/completions"
    assert seen["auth"] is None  # local servers need no key
    assert seen["body"]["stream"] is True and seen["body"]["model"] == "qwen2.5"
    assert seen["body"]["tools"] == [{"type": "function", "function": {
        "name": "get_weather", "description": "Weather.", "parameters": tool.parameters}}]


async def test_llm_handles_object_arguments_broken_json_and_errors():
    httpx = pytest.importorskip("httpx")
    from soro.adapters.composed.openai_compat_llm import OpenAICompatibleLLM

    def server(request):
        body = _sse(
            _delta(tool_calls=[{"id": "a", "function": {"name": "x", "arguments": {"k": 1}}}]),  # Ollama style
            _delta(tool_calls=[{"index": 1, "id": "b", "function": {"name": "y", "arguments": "{not json"}}]),
        )
        return httpx.Response(200, content=body)

    llm = OpenAICompatibleLLM(api_key="sk", transport=httpx.MockTransport(server))
    assert await _drain(llm) == [
        ToolCallRequest("a", "x", {"k": 1}),
        ToolCallRequest("b", "y", {"_raw_arguments": "{not json"}),
    ]

    failing = OpenAICompatibleLLM(transport=httpx.MockTransport(lambda r: httpx.Response(404, text="model not found")))
    with pytest.raises(RuntimeError, match="404: model not found"):
        await _drain(failing)


async def test_whisper_drops_segments_it_rates_as_not_speech(monkeypatch):
    """Whisper says "You" on silence; a high no_speech_prob segment must not become a user turn."""
    np = pytest.importorskip("numpy")
    from types import SimpleNamespace

    import soro.adapters.composed.faster_whisper_stt as whisper_module
    from soro.adapters.composed.faster_whisper_stt import FasterWhisperSTT

    monkeypatch.setattr(whisper_module, "_deps", lambda: (np, None))  # no faster-whisper needed

    class FakeModel:
        def transcribe(self, _audio, **_options):
            segments = [SimpleNamespace(text=" You", no_speech_prob=0.77),
                        SimpleNamespace(text=" Buy milk.", no_speech_prob=0.01)]
            return iter(segments), None

    stt = FasterWhisperSTT()
    stt._model = FakeModel()
    assert await stt.transcribe(b"\x00\x00" * 1600, 16_000) == "Buy milk."


def test_piper_sample_rate_is_read_from_the_voice_config(tmp_path):
    voice = tmp_path / "en_US-amy-medium.onnx"
    (tmp_path / "en_US-amy-medium.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 22050}}))
    assert voice_sample_rate(voice) == 22050
    with pytest.raises(FileNotFoundError):
        voice_sample_rate(tmp_path / "missing.onnx")


def test_create_composed_adapter_fails_early_without_its_pieces(monkeypatch):
    from soro.adapters.composed import create_composed_adapter

    monkeypatch.delenv("SORO_PIPER_VOICE", raising=False)
    with pytest.raises((ImportError, RuntimeError), match=r"soro\[composed\]|Piper voice"):
        create_composed_adapter()


def test_factory_knows_the_composed_provider(monkeypatch):
    from soro import create_live_adapter
    from soro.adapters.factory import PROVIDERS

    assert "composed" in PROVIDERS
    monkeypatch.delenv("SORO_PIPER_VOICE", raising=False)
    with pytest.raises((ImportError, RuntimeError)):
        create_live_adapter("composed")


async def test_faster_whisper_transcribes_silence_as_nothing():
    pytest.importorskip("faster_whisper")
    model = os.environ.get("SORO_TEST_WHISPER_MODEL")
    if not model:
        pytest.skip("set SORO_TEST_WHISPER_MODEL (e.g. tiny.en) to run against a real model")
    from soro.adapters.composed.faster_whisper_stt import FasterWhisperSTT

    stt = FasterWhisperSTT(model)
    assert await stt.transcribe(b"\x00\x00" * 16_000, 16_000) == ""
    with pytest.raises(ValueError):
        await stt.transcribe(b"\x00\x00", 8_000)


async def test_piper_synthesizes_audio_at_its_rate():
    pytest.importorskip("piper")
    voice = os.environ.get("SORO_TEST_PIPER_VOICE")
    if not voice:
        pytest.skip("set SORO_TEST_PIPER_VOICE to a voice .onnx to run against a real voice")
    from soro.adapters.composed.piper_tts import PiperTTS

    tts = PiperTTS(voice)
    pcm = b"".join([c async for c in tts.synthesize("Hello there.")])
    assert len(pcm) > tts.sample_rate * 2 * 0.2  # at least 200ms of speech
