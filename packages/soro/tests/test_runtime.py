"""
VoiceAgentRuntime and ToolRegistry, exercised with a small note-taker tool set
to show the runtime carries no use-case coupling.
"""

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

from soro.tools import ToolSpec
from soro.runtime import (
    RuntimeCallbacks,
    SessionComplete,
    ToolRegistry,
    VoiceAgentRuntime,
)
from soro.testing import FakeLiveAdapter

pytestmark = pytest.mark.unit

NOTE_DECL = {"name": "add_note", "description": "Save a note", "parameters": {"type": "object", "properties": {}}}
END_DECL = {"name": "end", "description": "End the call", "parameters": {"type": "object", "properties": {}}}


async def _mic(chunks=()):
    for c in chunks:
        yield c


def _runtime(adapter, tools=None, *, mic=(), opening=None, on_error=None, **cb):
    return VoiceAgentRuntime(
        adapter=adapter,
        system_prompt="you are a note taker",
        tools=tools or ToolRegistry(),
        audio_input_stream=_mic(mic),
        callbacks=RuntimeCallbacks(on_audio_output=cb.pop("on_audio_output", AsyncMock()), **cb),
        opening_message=opening,
        on_error=on_error,
    )


# ── ToolRegistry


def test_registry_exposes_neutral_specs():
    reg = ToolRegistry().register(NOTE_DECL, AsyncMock())
    assert reg.specs == [ToolSpec(name="add_note", description="Save a note", parameters=NOTE_DECL["parameters"])]
    assert "add_note" in reg


def test_registry_accepts_toolspec_directly():
    spec = ToolSpec(name="lookup", description="Find a fact")
    assert ToolRegistry().register(spec, AsyncMock()).specs == [spec]


def test_empty_registry_declares_no_tools():
    assert ToolRegistry().specs == []


def test_duplicate_registration_rejected():
    reg = ToolRegistry().register(NOTE_DECL, AsyncMock())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(NOTE_DECL, AsyncMock())


def test_from_declarations_requires_matching_handlers():
    tools = [{"function_declarations": [NOTE_DECL, END_DECL]}]
    with pytest.raises(ValueError, match="no handler for: \\['end'\\]"):
        ToolRegistry.from_declarations(tools, {"add_note": AsyncMock()})
    with pytest.raises(ValueError, match="no declaration for: \\['ghost'\\]"):
        ToolRegistry.from_declarations(
            tools, {"add_note": AsyncMock(), "end": AsyncMock(), "ghost": AsyncMock()}
        )


async def test_dispatch_unknown_tool_returns_error():
    result = await ToolRegistry().dispatch("nope", {})
    assert result == {"error": "Unknown tool: nope", "success": False}


# ── Runtime


async def test_run_passes_prompt_and_specs_and_sends_opening_message():
    adapter = FakeLiveAdapter()
    reg = ToolRegistry().register(NOTE_DECL, AsyncMock())
    await _runtime(adapter, reg, opening="hello").run()
    assert adapter.open_args == ("you are a note taker", reg.specs)
    assert adapter.content == ["hello"]
    assert adapter.closed_count == 1


async def test_no_opening_message_means_nothing_is_sent():
    adapter = FakeLiveAdapter()
    await _runtime(adapter).run()
    assert adapter.content == []


async def test_custom_tool_result_returned_to_model():
    handler = AsyncMock(return_value={"success": True, "saved": 1})
    reg = ToolRegistry().register(NOTE_DECL, handler)
    adapter = FakeLiveAdapter(events=[("tool_call", {"id": "1", "name": "add_note", "args": {"text": "x"}})])

    await _runtime(adapter, reg).run()

    handler.assert_awaited_once_with({"text": "x"})
    assert adapter.tool_responses == [{"call_id": "1", "name": "add_note", "result": {"success": True, "saved": 1}}]


async def test_handler_raising_session_complete_ends_run_normally():
    async def end(_args):
        raise SessionComplete("hung_up")

    reg = ToolRegistry().register(END_DECL, end)
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "1", "name": "end", "args": {}}), ("audio", b"never")],
    )
    on_audio = AsyncMock()
    rt = _runtime(adapter, reg, on_audio_output=on_audio)

    await rt.run()

    assert rt.end_reason == "hung_up"
    assert adapter.tool_responses == []
    on_audio.assert_not_awaited()


async def test_handler_error_returned_to_model_and_on_error_not_called():
    async def boom(_args):
        raise RuntimeError("db down")

    on_error = AsyncMock()
    reg = ToolRegistry().register(NOTE_DECL, boom)
    adapter = FakeLiveAdapter(events=[("tool_call", {"id": "1", "name": "add_note", "args": {}})])

    await _runtime(adapter, reg, on_error=on_error).run()

    assert adapter.tool_responses[0]["result"] == {"error": "db down", "success": False}
    on_error.assert_not_awaited()


async def test_session_failure_calls_on_error_then_reraises():
    class Boom(FakeLiveAdapter):
        async def receive(self):
            raise ConnectionError("socket died")
            yield  # pragma: no cover

    on_error = AsyncMock()
    with pytest.raises(ConnectionError):
        await _runtime(Boom(), on_error=on_error).run()
    assert isinstance(on_error.await_args.args[0], ConnectionError)


async def test_stop_from_handler_lets_response_go_out_then_exits():
    holder = {}

    async def note(_args):
        holder["rt"].stop("done")
        return {"success": True}

    reg = ToolRegistry().register(NOTE_DECL, note)
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "1", "name": "add_note", "args": {}}), ("audio", b"late")]
    )
    on_audio = AsyncMock()
    rt = holder["rt"] = _runtime(adapter, reg, on_audio_output=on_audio)

    await rt.run()

    assert adapter.tool_responses[0]["result"] == {"success": True}
    assert rt.end_reason == "done" and rt.is_complete
    on_audio.assert_not_awaited()


async def test_ending_one_loop_cancels_the_other():
    """A mic that never ends must not keep the session alive after the model closes."""
    cancelled = asyncio.Event()

    async def endless_mic():
        try:
            while True:
                yield b""
                await asyncio.sleep(0.01)
        finally:
            cancelled.set()

    rt = VoiceAgentRuntime(
        adapter=FakeLiveAdapter(events=[("session_ending", {"reason": "test"})]),
        system_prompt="p",
        tools=ToolRegistry(),
        audio_input_stream=endless_mic(),
        callbacks=RuntimeCallbacks(on_audio_output=AsyncMock()),
    )
    await asyncio.wait_for(rt.run(), timeout=2)
    assert cancelled.is_set()


async def test_cancelling_run_cancels_both_loops_and_closes_session():
    async def endless_mic():
        while True:
            await asyncio.sleep(0.01)
            yield b""

    adapter = FakeLiveAdapter(hold_open_until_audio=1)  # receive never finishes
    rt = VoiceAgentRuntime(
        adapter=adapter,
        system_prompt="p",
        tools=ToolRegistry(),
        audio_input_stream=endless_mic(),
        callbacks=RuntimeCallbacks(on_audio_output=AsyncMock()),
    )
    task = asyncio.create_task(rt.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert adapter.closed_count == 1


def test_the_sdk_never_imports_an_application():
    """Soro is a library: it must not depend on any app built on top of it."""
    import ast
    import pathlib

    import soro

    root = pathlib.Path(soro.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] in ("src", "truefit_core", "truefit_infra", "truefit_api")]
    assert offenders == []



# ── Reconnect recovery

def _resume_runtime(adapter, **kw):
    return VoiceAgentRuntime(
        adapter=adapter,
        system_prompt="p",
        tools=ToolRegistry(),
        audio_input_stream=_mic(),
        callbacks=RuntimeCallbacks(on_audio_output=AsyncMock(), **kw),
        resume_message="Sorry, the line dropped. Please repeat your last answer.",
    )


async def test_a_resumed_session_asks_the_user_to_repeat_and_flushes_stale_audio():
    adapter = FakeLiveAdapter(events=[("session_resumed", {"reason": "connection_error", "restarted": False})])
    on_interrupt = AsyncMock()
    await _resume_runtime(adapter, on_interrupt=on_interrupt).run()
    assert adapter.content == ["Sorry, the line dropped. Please repeat your last answer."]
    on_interrupt.assert_awaited_once()


async def test_a_restarted_session_does_not_send_the_repeat_your_answer_nudge():
    """Regression: after a restart the opening message is replayed, so the nudge made the
    agent apologise for a dropped answer in a conversation that had only just begun."""
    adapter = FakeLiveAdapter(events=[("session_resumed", {"reason": "connection_error", "restarted": True})])
    on_interrupt = AsyncMock()
    await _resume_runtime(adapter, on_interrupt=on_interrupt).run()
    assert adapter.content == []
    on_interrupt.assert_awaited_once()  # the half-spoken greeting is still dropped


async def test_session_resumed_without_a_payload_is_treated_as_resumed():
    adapter = FakeLiveAdapter(events=[("session_resumed", None)])
    await _resume_runtime(adapter).run()
    assert adapter.content == ["Sorry, the line dropped. Please repeat your last answer."]


async def test_session_resumed_is_silent_without_a_resume_message():
    adapter = FakeLiveAdapter(events=[("session_resumed", {"reason": "go_away", "restarted": False}), ("audio", b"x")])
    on_audio = AsyncMock()
    await _runtime(adapter, on_audio_output=on_audio).run()
    assert adapter.content == []
    on_audio.assert_awaited_once()
