# Soro

Model-agnostic realtime voice agent infrastructure.

Write an agent once (a prompt, some tools, audio in and out) and run it on any realtime model. Soro gives you one small interface, `LiveSessionPort`, and adapters that implement it for each provider. Your agent never touches a provider SDK, so switching from Gemini Live to OpenAI Realtime, or failing over between them, is a configuration change.

> **Status: 0.1, alpha.** The interface may still change while the second (composed, non-native-audio) approach is built and validated against it. Pin the exact version.

## Install

```bash
pip install "soro[gemini]"       # Gemini Live
pip install "soro[openai]"       # OpenAI Realtime
pip install "soro[all]"          # both
```

Each provider's SDK is imported lazily, so you only need the extras you use.

## A minimal agent

```python
import asyncio
from soro import RuntimeCallbacks, ToolRegistry, ToolSpec, VoiceAgentRuntime, create_live_adapter

notes: list[str] = []

async def save_note(args: dict) -> dict:
    notes.append(args["text"])
    return {"success": True}

async def play(pcm: bytes) -> None:   # 24kHz mono s16 PCM from the model
    ...

async def mic():                      # yield 16kHz mono s16 PCM chunks
    ...
    yield b""

async def main():
    runtime = VoiceAgentRuntime(
        adapter=create_live_adapter("gemini", fallback="openai",
                                    gemini_api_key="...", openai_api_key="..."),
        system_prompt="You are a note taker. Save anything the user asks you to remember.",
        tools=ToolRegistry().register(
            ToolSpec(
                name="save_note",
                description="Save a note for the user.",
                parameters={"type": "object", "properties": {"text": {"type": "string"}},
                            "required": ["text"]},
            ),
            save_note,
        ),
        audio_input_stream=mic(),
        callbacks=RuntimeCallbacks(on_audio_output=play),
        opening_message="Greet the user and ask what they want to remember.",
    )
    await runtime.run()

asyncio.run(main())
```

## Concepts

- **`LiveSessionPort`** is the interface every adapter implements. It emits normalised `(event_type, data)` events: `audio`, `text`, `input_text`, `tool_call`, `turn_complete`, `interrupted`, `session_ending`, `session_resumed`.
- **`AdapterCapabilities`** says what an adapter can do: sample rates, image input, whether the provider does its own turn detection. Read it instead of assuming.
- **`ToolSpec`** describes a tool once. Each adapter translates it to its provider's format.
- **`ToolRegistry`** keeps each tool's declaration and handler together.
- **`VoiceAgentRuntime`** runs the send and receive loops, routes events to your callbacks, dispatches tool calls, and ends the session when a handler raises `SessionComplete`.
- **`FallbackLiveAdapter`** wraps two adapters and continues on the second if the first fails to open or fails before it produces any output.

## Resilience

The Gemini adapter uses session resumption: a dropped connection, a transient server error, or Gemini's periodic connection recycle continues the same conversation. After a reconnect the adapter emits `session_resumed`, and the runtime sends your `resume_message` because the user's last turn may have been lost.

## Testing your agent

```python
from soro.testing import FakeLiveAdapter

adapter = FakeLiveAdapter(events=[("tool_call", {"id": "1", "name": "save_note", "args": {"text": "milk"}})])
```

`FakeLiveAdapter` needs no network or API key and records everything your agent sends.

## Configuration

Adapters take their settings as constructor arguments and fall back to the provider's usual environment variables (`GEMINI_API_KEY`, `GEMINI_LIVE_MODEL`, `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL`). Soro reads no other global configuration.

## Develop

```bash
pip install -e ".[dev]"
pytest
```

## Turn detection

`soro.audio` has a `TurnDetector` protocol and an `EnergyTurnDetector`. Feed it 16-bit mono PCM chunks and it returns a `TurnEvent("start" | "end")` at turn boundaries. It learns a noise floor, so steady noise such as a fan does not hold a turn open, and it uses separate start and end thresholds so a level near the edge does not flap. Providers with their own detection do not need one (`capabilities.native_vad`).
