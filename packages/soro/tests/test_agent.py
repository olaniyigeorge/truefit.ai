"""Agent facade end to end on FakeLiveAdapter: connectors in, policy applied, connectors closed."""

from __future__ import annotations

import asyncio

import pytest

from soro import Agent, SessionComplete, ToolSpec
from soro.connectors import functions
from soro.runtime.policy import CONFIRM_INSTRUCTIONS
from soro.testing import FakeLiveAdapter

pytestmark = pytest.mark.unit


async def _mic(n=1):
    for _ in range(n):
        yield b"\x00\x00" * 320


async def _play(pcm: bytes) -> None:
    pass


class RecordingConnector:
    def __init__(self, pairs=()):
        self.pairs = list(pairs)
        self.opened = 0
        self.closed = 0

    async def tools(self):
        self.opened += 1
        return self.pairs

    async def aclose(self):
        self.closed += 1


async def test_tools_from_connectors_run_and_connectors_close():
    notes: list[str] = []

    def save_note(text: str) -> None:
        """Save a note."""
        notes.append(text)

    async def end_call() -> None:
        """Hang up."""
        raise SessionComplete("bye")

    extra = RecordingConnector()
    adapter = FakeLiveAdapter(events=[
        ("tool_call", {"id": "1", "name": "save_note", "args": {"text": "milk"}}),
        ("tool_call", {"id": "2", "name": "end_call", "args": {}}),
    ], hold_open_until_audio=1)
    agent = Agent(prompt="Take notes.", connectors=[extra], tools=[save_note, end_call],
                  adapter=adapter, opening_message="Hi")

    reason = await agent.run(audio_input_stream=_mic(), on_audio_output=_play)

    assert reason == "bye"
    assert notes == ["milk"]
    assert adapter.tool_responses[0] == {"call_id": "1", "name": "save_note", "result": {"success": True}}
    prompt, specs = adapter.open_args
    assert prompt == "Take notes."  # no policy, no appended conventions
    assert [s.name for s in specs] == ["save_note", "end_call"]
    assert adapter.content == ["Hi"]
    assert (extra.opened, extra.closed) == (1, 1)


async def test_confirm_policy_guards_the_tool_and_extends_the_prompt():
    deleted: list[str] = []

    def delete_note(note_id: str) -> None:
        """Delete a note."""
        deleted.append(note_id)

    adapter = FakeLiveAdapter(events=[
        ("tool_call", {"id": "1", "name": "delete_note", "args": {"note_id": "a"}}),
        ("tool_call", {"id": "2", "name": "delete_note", "args": {"note_id": "a", "confirmed": True}}),
    ], hold_open_until_audio=1)
    agent = Agent(prompt="P", tools=[delete_note], confirm=["delete_*"], adapter=adapter)
    await agent.run(audio_input_stream=_mic(), on_audio_output=_play)

    prompt, specs = adapter.open_args
    assert prompt == f"P\n\n{CONFIRM_INSTRUCTIONS}"
    assert "confirmed" in specs[0].parameters["required"]
    assert adapter.tool_responses[0]["result"]["needs_confirmation"] is True
    assert adapter.tool_responses[1]["result"] == {"success": True}
    assert deleted == ["a"]


async def test_background_result_is_injected_into_the_open_session():
    async def research(topic: str) -> dict:
        """Slow lookup."""
        await asyncio.sleep(0.01)
        return {"summary": f"all about {topic}"}

    # Keep the session open long enough for the background task to report back.
    adapter = FakeLiveAdapter(events=[
        ("tool_call", {"id": "1", "name": "research", "args": {"topic": "bees"}}),
    ], hold_open_until_audio=6)

    async def slow_mic():
        for _ in range(6):
            await asyncio.sleep(0.01)
            yield b"\x00\x00" * 320

    agent = Agent(prompt="P", tools=[research], background=["research"], adapter=adapter)
    await agent.run(audio_input_stream=slow_mic(), on_audio_output=_play)

    assert adapter.tool_responses[0]["result"]["status"] == "started"
    assert adapter.content == ['[tool result] research finished: {"summary": "all about bees"}']


async def test_connectors_close_even_when_the_session_fails():
    conn = RecordingConnector([(ToolSpec(name="x"), _noop)])
    adapter = FakeLiveAdapter(events=[RuntimeError("provider died")])
    agent = Agent(prompt="P", connectors=[conn], adapter=adapter)
    with pytest.raises(RuntimeError, match="provider died"):
        await agent.run(audio_input_stream=_mic(), on_audio_output=_play)
    assert conn.closed == 1


async def test_tools_preview_opens_and_closes_connectors():
    conn = RecordingConnector([(ToolSpec(name="delete_all"), _noop)])
    agent = Agent(prompt="P", connectors=[conn], confirm=["delete_*"], adapter=FakeLiveAdapter())
    [(spec, _)] = await agent.tools()
    assert "confirmed" in spec.parameters["properties"]
    assert (conn.opened, conn.closed) == (1, 1)


def test_adapter_and_provider_are_exclusive():
    with pytest.raises(ValueError):
        Agent(prompt="P", adapter=FakeLiveAdapter(), provider="gemini")


async def test_provider_builds_through_the_factory(monkeypatch):
    from soro.adapters import factory

    built = []

    def fake_create(primary, fallback, **opts):
        built.append((primary, fallback, opts))
        return FakeLiveAdapter()

    monkeypatch.setattr(factory, "create_live_adapter", fake_create)
    agent = Agent(prompt="P", provider="openai", openai_api_key="k")
    await agent.run(audio_input_stream=_mic(), on_audio_output=_play)
    assert built == [("openai", None, {"openai_api_key": "k"})]


async def _noop(args):
    return {}
