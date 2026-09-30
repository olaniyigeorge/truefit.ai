# Soro

Model-agnostic realtime voice agent infrastructure.

Write an agent once (a prompt, some tools, audio in and out) and run it on any realtime model. Soro gives you one small interface, `LiveSessionPort`, and adapters that implement it for each provider. Your agent never touches a provider SDK, so switching from Gemini Live to OpenAI Realtime, or failing over between them, is a configuration change.

> **Status: 0.1, alpha.** The interface may still change while the second (composed, non-native-audio) approach is built and validated against it. Pin the exact version.

## Install

```bash
pip install soro                 # core only: port, runtime, tools, turn detection, test doubles
pip install "soro[gemini]"       # + Gemini Live
pip install "soro[openai]"       # + OpenAI Realtime
pip install "soro[webrtc]"       # + WebRTC audio transport (aiortc)
pip install "soro[all]"          # everything
```

Each provider's SDK is imported lazily, so you only need the extras you use. If you ask for a provider whose extra is missing, Soro tells you which one to install.

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

## Turn detection

Providers with their own voice activity detection (`capabilities.native_vad`) need nothing here. When you run the detection yourself, `soro.audio` has a `TurnDetector` protocol and an `EnergyTurnDetector`:

```python
from soro.audio import EnergyTurnDetector

detector = EnergyTurnDetector()
for chunk in mic_chunks:                # 16-bit mono PCM, any chunk size
    event = detector.process(chunk)
    if event:
        print(event.kind)               # "start" or "end"
```

It learns a noise floor, so steady noise such as a fan raises the floor instead of holding a turn open. It uses separate start and end thresholds so a level near the edge does not flap, and it tolerates the short gaps between syllables. Time is measured in audio, not wall clock, so it is deterministic. Tune it with `EnergyTurnConfig` (for example `end_ms`). Anything that implements the protocol can replace it, such as a neural detector.

## WebRTC transport

`soro.transport.webrtc.AudioBridge` connects a WebRTC peer connection (aiortc) to a voice agent. It resamples browser audio to 16kHz for the agent, paces the agent's audio back out as a WebRTC track, gates the mic while the agent speaks, suppresses echo, and uses a turn detector to call your `_on_activity_start` and `_on_activity_end` callbacks. Install it with `pip install "soro[webrtc]"`.

```python
from soro.transport.webrtc import AudioBridge

bridge = AudioBridge(session_id="abc", output_sample_rate=adapter.capabilities.output_sample_rate)
peer_connection.addTrack(bridge.create_outbound_track())
await bridge.attach_inbound_track(browser_audio_track)
bridge.open_mic()
# pass bridge.audio_input_stream() to VoiceAgentRuntime, and push_audio() the model's audio back
```

## Testing your agent

```python
from soro.testing import FakeLiveAdapter

adapter = FakeLiveAdapter(events=[("tool_call", {"id": "1", "name": "save_note", "args": {"text": "milk"}})])
```

`FakeLiveAdapter` needs no network or API key and records everything your agent sends. See `examples/offline_note_taker.py` for a complete run.

## Examples

| File | Shows |
|---|---|
| `examples/offline_note_taker.py` | An agent with tools, run end to end with no network or key |
| `examples/turn_detection.py` | The detector ignoring a fan and finding speech over it |

## Resilience

The Gemini adapter uses session resumption: a dropped connection, a transient server error, or Gemini's periodic connection recycle continues the same conversation. After a reconnect the adapter emits `session_resumed`, and the runtime sends your `resume_message` because the user's last turn may have been lost. `FallbackLiveAdapter` (what `create_live_adapter` returns when you pass a `fallback`) continues on the second provider if the first fails to open or fails before it produces any output.

## Configuration

Adapters take their settings as constructor arguments and fall back to the provider's usual environment variables (`GEMINI_API_KEY`, `GEMINI_LIVE_MODEL`, `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL`). Soro reads no other global configuration.

## Develop

```bash
pip install -e ".[dev]"
pytest
```

Before a release, check the built package the way a user gets it:

```bash
EXTRAS=gemini,openai,webrtc scripts/test_from_testpypi.sh local              # build, twine check, clean venv, smoke test
twine upload -r testpypi dist/*                                               # then:
EXTRAS=gemini,openai,webrtc scripts/test_from_testpypi.sh testpypi 0.1.0     # install from TestPyPI and smoke test
```

`scripts/smoke_test.py` runs against the installed package and needs no key. Set `GEMINI_API_KEY` or `OPENAI_API_KEY` and it also opens a real session.
