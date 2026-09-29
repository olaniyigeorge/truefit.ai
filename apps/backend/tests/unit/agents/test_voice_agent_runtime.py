"""
VoiceAgentRuntime and ToolRegistry, exercised with a non-interview tool set
(a note-taker) to show the runtime has no interview coupling.
"""

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

from src.truefit_core.agents.runtime import (
    RuntimeCallbacks,
    SessionComplete,
    ToolRegistry,
    VoiceAgentRuntime,
)
from tests.unit.llm.fakes import FakeLiveAdapter

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


def test_registry_declarations_use_adapter_format():
    reg = ToolRegistry().register(NOTE_DECL, AsyncMock())
    assert reg.declarations == [{"function_declarations": [NOTE_DECL]}]
    assert "add_note" in reg


def test_empty_registry_declares_no_tools():
    assert ToolRegistry().declarations == []


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


async def test_run_passes_prompt_and_declarations_and_sends_opening_message():
    adapter = FakeLiveAdapter()
    reg = ToolRegistry().register(NOTE_DECL, AsyncMock())
    await _runtime(adapter, reg, opening="hello").run()
    assert adapter.open_args == ("you are a note taker", reg.declarations)
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
        adapter=FakeLiveAdapter(events=[("go_away", None)]),
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


def test_runtime_imports_only_the_port_never_infra_or_interview_code():
    import ast

    import src.truefit_core.agents.runtime.runtime as rt_mod
    import src.truefit_core.agents.runtime.tools as tools_mod

    for mod in (rt_mod, tools_mod):
        imported = set()
        for node in ast.walk(ast.parse(open(mod.__file__).read())):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        forbidden = [
            m for m in imported
            if "truefit_infra" in m or "interviewer" in m or "services" in m or "domain" in m
        ]
        assert forbidden == []
