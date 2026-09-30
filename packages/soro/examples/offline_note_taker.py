"""
A note-taking agent that runs with no network and no API key.

FakeLiveAdapter stands in for the model: it "decides" to call save_note, the
runtime runs your handler and sends the result back. Swap the adapter for
create_live_adapter("gemini", gemini_api_key=...) to talk to a real model.

    python examples/offline_note_taker.py
"""

import asyncio

from soro import RuntimeCallbacks, SessionComplete, ToolRegistry, ToolSpec, VoiceAgentRuntime
from soro.testing import FakeLiveAdapter

notes: list[str] = []


async def save_note(args: dict) -> dict:
    notes.append(args["text"])
    return {"success": True}


async def end_call(args: dict) -> dict:
    raise SessionComplete("done")


async def mic():
    yield b"\x00\x00" * 320  # one 20ms chunk of 16kHz silence


async def play(pcm: bytes) -> None:
    pass


async def main() -> None:
    adapter = FakeLiveAdapter(
        events=[
            ("tool_call", {"id": "1", "name": "save_note", "args": {"text": "buy milk"}}),
            ("tool_call", {"id": "2", "name": "end_call", "args": {}}),
        ],
        hold_open_until_audio=1,
    )
    tools = (
        ToolRegistry()
        .register(
            ToolSpec(
                name="save_note",
                description="Save a note for the user.",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            save_note,
        )
        .register(ToolSpec(name="end_call", description="End the conversation."), end_call)
    )
    runtime = VoiceAgentRuntime(
        adapter=adapter,
        system_prompt="You are a note taker.",
        tools=tools,
        audio_input_stream=mic(),
        callbacks=RuntimeCallbacks(on_audio_output=play),
    )
    await runtime.run()
    print("notes:", notes)
    assert notes == ["buy milk"]


asyncio.run(main())
