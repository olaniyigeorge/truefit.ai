"""
A connected agent: tools from plain functions and an OpenAPI spec, with the voice
policy applied, running with no network and no API key.

The "model" is a FakeLiveAdapter that asks to delete a note without confirming
(the policy refuses), confirms, then kicks off a slow search that runs in the
background while the conversation carries on. The OpenAPI connector talks to a
stub served by httpx.MockTransport instead of a real server.

Swap adapter= for provider="gemini" (and a key) to talk to a real model, and the
spec dict for your service's openapi.json URL.

    python examples/connected_agent.py
"""

import asyncio

import httpx

import soro
from soro.testing import FakeLiveAdapter

notes = {"1": "buy milk", "2": "call mum"}


@soro.tool
def list_notes() -> list[str]:
    """List the user's notes."""
    return list(notes.values())


@soro.tool
def delete_note(note_id: str) -> str:
    """
    Delete one note.

    Args:
        note_id: The id of the note to delete.
    """
    return notes.pop(note_id, "no such note")


async def search_web(query: str) -> dict:
    """Search the web (slow, so it runs in the background)."""
    await asyncio.sleep(0.05)
    return {"top_result": f"Everything about {query}"}


async def end_call() -> None:
    """End the conversation."""
    raise soro.SessionComplete("done")


WEATHER_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Weather", "version": "1"},
    "servers": [{"url": "https://weather.example"}],
    "paths": {
        "/forecast": {
            "get": {
                "operationId": "get_forecast",
                "summary": "Tomorrow's forecast for a city.",
                "parameters": [
                    {"name": "city", "in": "query", "required": True, "schema": {"type": "string"}}
                ],
            }
        }
    },
}


def weather_stub(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"city": request.url.params["city"], "forecast": "sunny"})


async def main() -> None:
    model = FakeLiveAdapter(
        events=[
            ("tool_call", {"id": "1", "name": "delete_note", "args": {"note_id": "1"}}),
            (
                "tool_call",
                {"id": "2", "name": "delete_note", "args": {"note_id": "1", "confirmed": True}},
            ),
            ("tool_call", {"id": "3", "name": "get_forecast", "args": {"city": "Lagos"}}),
            ("tool_call", {"id": "4", "name": "search_web", "args": {"query": "bees"}}),
        ],
        hold_open_until_audio=8,  # keep talking while the background search finishes
    )

    agent = soro.Agent(
        prompt="You are my assistant. You can manage my notes and check the weather.",
        tools=[list_notes, delete_note, search_web, end_call],
        connectors=[
            soro.connectors.openapi(WEATHER_SPEC, transport=httpx.MockTransport(weather_stub))
        ],
        confirm=["delete_*"],
        background=["search_*"],
        adapter=model,
    )

    async def mic():
        for _ in range(8):
            await asyncio.sleep(0.02)
            yield b"\x00\x00" * 320

    async def play(pcm: bytes) -> None:
        pass

    print("tools:", [spec.name for spec, _ in await agent.tools()])
    await agent.run(audio_input_stream=mic(), on_audio_output=play)

    for response in model.tool_responses:
        print(f"{response['name']:>13} -> {response['result']}")
    print("injected:", model.content)
    print("notes left:", notes)

    assert model.tool_responses[0]["result"]["needs_confirmation"] is True
    assert notes == {"2": "call mum"}
    assert model.tool_responses[2]["result"]["data"]["forecast"] == "sunny"
    assert model.content and model.content[0].startswith("[tool result] search_web finished")


asyncio.run(main())
