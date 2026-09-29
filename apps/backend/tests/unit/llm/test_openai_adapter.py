"""OpenAIRealtimeAdapter behaviour that needs no network."""

from types import SimpleNamespace

import pytest
from websockets.protocol import State

from src.truefit_infra.llm.openai_realtime import OpenAIRealtimeAdapter

pytestmark = pytest.mark.unit


async def test_is_healthy_false_without_a_session():
    assert await OpenAIRealtimeAdapter(api_key="k").is_healthy() is False


@pytest.mark.parametrize(
    "state,expected",
    [(State.OPEN, True), (State.CLOSING, False), (State.CLOSED, False)],
)
async def test_is_healthy_reads_the_websocket_state(state, expected):
    """Regression: is_healthy used ws.open, which websockets 16 no longer has."""
    adapter = OpenAIRealtimeAdapter(api_key="k")
    adapter._ws = SimpleNamespace(state=state)
    assert await adapter.is_healthy() is expected


# ── GA protocol (the beta protocol was switched off by OpenAI)

import base64
import json
import math
import struct

from src.truefit_core.application.tools import ToolSpec
from src.truefit_infra.config import AppConfig
from src.truefit_infra.llm import openai_realtime


class FakeWS:
    """Records what the adapter sends and replays scripted server events."""

    def __init__(self, server_events=()):
        self.sent: list[dict] = []
        self._events = [json.dumps(e) for e in server_events]
        self.state = State.OPEN

    async def send(self, raw: str):
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e

        return gen()


def _tone(n: int) -> bytes:
    return struct.pack(f"<{n}h", *[int(8000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(n)])


async def _events(server_events):
    adapter = OpenAIRealtimeAdapter(api_key="k")
    adapter._ws = FakeWS(server_events)
    return [e async for e in adapter.receive()]


@pytest.fixture
def connect_spy(monkeypatch):
    seen = {}
    ws = FakeWS()

    class CM:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *a):
            return None

    def fake_connect(url, additional_headers=None, **kw):
        seen["url"], seen["headers"] = url, additional_headers
        return CM()

    monkeypatch.setattr(openai_realtime.websockets, "connect", fake_connect)
    seen["ws"] = ws
    return seen


async def test_connects_without_the_beta_header(connect_spy):
    adapter = OpenAIRealtimeAdapter(api_key="secret")
    async with adapter.open_session("prompt"):
        pass
    assert connect_spy["headers"] == {"Authorization": "Bearer secret"}
    assert "OpenAI-Beta" not in connect_spy["headers"]
    assert connect_spy["url"].startswith("wss://api.openai.com/v1/realtime?model=")


async def test_model_can_be_overridden(connect_spy, monkeypatch):
    monkeypatch.setattr(AppConfig, "OPENAI_REALTIME_MODEL", "gpt-realtime-2.1-mini", raising=False)
    async with OpenAIRealtimeAdapter(api_key="k").open_session("p"):
        pass
    assert connect_spy["url"].endswith("?model=gpt-realtime-2.1-mini")


async def test_session_update_uses_the_ga_shape(connect_spy):
    tool = ToolSpec(name="record", description="d", parameters={"type": "object", "properties": {}})
    async with OpenAIRealtimeAdapter(api_key="k").open_session("be brief", tools=[tool]):
        pass
    update = connect_spy["ws"].sent[0]
    assert update["type"] == "session.update"
    s = update["session"]
    assert s["type"] == "realtime"
    assert s["instructions"] == "be brief"
    assert s["output_modalities"] == ["audio"]  # GA rejects audio+text together
    assert s["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["input"]["turn_detection"] is None  # manual turns
    assert s["audio"]["input"]["transcription"]["model"]
    assert s["audio"]["output"]["voice"]
    assert s["tools"] == [
        {"type": "function", "name": "record", "description": "d", "parameters": tool.parameters}
    ]
    # beta-only keys must be gone
    for beta_key in ("modalities", "voice", "input_audio_format", "output_audio_format", "turn_detection"):
        assert beta_key not in s


async def test_send_audio_upsamples_16k_to_24k_before_sending():
    adapter = OpenAIRealtimeAdapter(api_key="k")
    adapter._ws = ws = FakeWS()
    for _ in range(10):
        await adapter.send_audio(_tone(320))  # 20ms at 16kHz each
    appends = [m for m in ws.sent if m["type"] == "input_audio_buffer.append"]
    total_bytes = sum(len(base64.b64decode(m["audio"])) for m in appends)
    assert abs(total_bytes / 2 - 10 * 480) < 60  # 1.5x the input, not the raw 16kHz


async def test_send_audio_after_activity_end_is_dropped():
    adapter = OpenAIRealtimeAdapter(api_key="k")
    adapter._ws = ws = FakeWS()
    await adapter.send_activity_end()
    ws.sent.clear()
    await adapter.send_audio(_tone(320))
    assert ws.sent == []


async def test_audio_and_transcript_events_use_the_ga_names():
    pcm = b"\x01\x02" * 10
    events = await _events(
        [
            {"type": "response.created", "response": {"id": "r1"}},
            {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
            {"type": "response.output_audio_transcript.delta", "delta": "Hello "},
            {"type": "response.output_audio_transcript.done", "transcript": "Hello there"},
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "hi"},
            {"type": "response.done", "response": {"status": "completed"}},
        ]
    )
    assert events == [
        ("audio", pcm),
        ("input_text", "hi"),
        ("text", "Hello there"),
        ("turn_complete", None),
    ]


async def test_beta_transcript_event_names_no_longer_produce_text():
    events = await _events(
        [
            {"type": "response.audio_transcript.done", "transcript": "ignored"},
            {"type": "response.done", "response": {"status": "completed"}},
        ]
    )
    assert events == [("turn_complete", None)]


async def test_function_call_item_becomes_a_tool_call():
    events = await _events(
        [
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "name": "record_question", "call_id": "c1", "arguments": '{"topic": "apis"}'},
            }
        ]
    )
    assert events == [("tool_call", {"id": "c1", "name": "record_question", "args": {"topic": "apis"}})]


async def test_bad_tool_arguments_become_empty_args_not_a_crash():
    events = await _events(
        [{"type": "response.output_item.done", "item": {"type": "function_call", "name": "n", "call_id": "c", "arguments": "{oops"}}]
    )
    assert events == [("tool_call", {"id": "c", "name": "n", "args": {}})]


async def test_tool_result_is_returned_as_a_function_call_output_then_response_create():
    adapter = OpenAIRealtimeAdapter(api_key="k")
    adapter._ws = ws = FakeWS()
    await adapter.send_tool_response(call_id="c1", name="n", result={"success": True})
    assert ws.sent[0] == {
        "type": "conversation.item.create",
        "item": {"type": "function_call_output", "call_id": "c1", "output": json.dumps({"success": True})},
    }
    assert ws.sent[1] == {"type": "response.create"}


@pytest.mark.parametrize(
    "response,expected",
    [
        ({"status": "completed"}, "turn_complete"),
        ({"status": "cancelled"}, "interrupted"),
        ({"status": "failed"}, "interrupted"),
        ({"status": "incomplete", "status_details": {"reason": "turn_detected"}}, "interrupted"),
        ({"status": "incomplete", "status_details": {"reason": "client_cancelled"}}, "interrupted"),
        # Regression: these used to yield nothing and leave the agent waiting forever.
        ({"status": "incomplete", "status_details": {"reason": "max_output_tokens"}}, "turn_complete"),
        ({"status": "incomplete", "status_details": {"reason": "content_filter"}}, "turn_complete"),
        ({"status": "incomplete"}, "turn_complete"),
    ],
)
async def test_response_done_statuses(response, expected):
    events = await _events([{"type": "response.done", "response": response}])
    assert events == [(expected, None)]


async def test_speech_started_only_interrupts_an_active_response():
    idle = await _events([{"type": "input_audio_buffer.speech_started"}])
    assert idle == []
    active = await _events(
        [
            {"type": "response.created", "response": {"id": "r"}},
            {"type": "input_audio_buffer.speech_started"},
        ]
    )
    assert active == [("interrupted", None)]


async def test_api_error_event_raises_with_the_server_message():
    with pytest.raises(RuntimeError, match="beta_api_shape_disabled"):
        await _events([{"type": "error", "error": {"code": "beta_api_shape_disabled", "message": "no"}}])


async def test_unknown_events_are_ignored():
    assert await _events([{"type": "rate_limits.updated", "rate_limits": []}, {"type": "something.new"}]) == []
