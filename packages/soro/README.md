# Soro

Model-agnostic realtime voice agent infrastructure.

Write an agent once (a prompt, some tools, audio in and out) and run it on any realtime model. Soro gives you one small interface, `LiveSessionPort`, and adapters that implement it for each provider. Your agent never touches a provider SDK, so switching from Gemini Live to OpenAI Realtime, or failing over between them, is a configuration change.

> **Status: 0.1, alpha.** The composed (non-native-audio) adapter has run live end to end against local models (spoken audio in, a tool call, spoken audio out); see "Measured on a laptop CPU" below. The interface may still change. Pin the exact version.

## Install

```bash
pip install soro                 # core only: port, runtime, tools, turn detection, test doubles
pip install "soro[gemini]"       # + Gemini Live
pip install "soro[openai]"       # + OpenAI Realtime
pip install "soro[webrtc]"       # + WebRTC audio transport (aiortc)
pip install "soro[vad]"          # + Silero neural turn detection (onnxruntime, no torch)
pip install "soro[openapi]"      # + OpenAPI connector (httpx, pyyaml)
pip install "soro[mcp]"          # + MCP connector
pip install "soro[composed]"     # + local STT -> LLM -> TTS adapter (faster-whisper, Piper)
pip install "soro[all]"          # everything
```

Each provider's SDK is imported lazily, so you only need the extras you use. If you ask for a provider whose extra is missing, Soro tells you which one to install.

## An agent in a few lines

`Agent` is the quickest start: a prompt, tools from connectors, and a voice policy.

```python
import soro

@soro.tool
def save_note(text: str) -> None:
    """Save a note for the user.

    Args:
        text: What to write down.
    """
    ...

agent = soro.Agent(
    prompt="You are my assistant. You can manage my notes and calendar.",
    tools=[save_note],                                         # plain functions
    connectors=[soro.connectors.openapi("https://my-os.example/openapi.json"),
                soro.connectors.mcp("python calendar_server.py")],
    confirm=["delete_*", "schedule_*"],                        # ask aloud before running
    background=["search_*"],                                   # slow: acknowledge now, report later
    provider="gemini", gemini_api_key="...",
)
await agent.run(audio_input_stream=mic(), on_audio_output=play)
```

- **Connectors** turn an existing system into tools. `functions(...)` reads the signature and docstring, so the schema cannot drift from the code. `openapi(spec)` makes one tool per operation and calls the API (allowlist with `operations=` or `tags=`, auth with `headers=`). `mcp(command_or_url)` proxies an MCP server's tools over stdio or HTTP. Anything with async `tools()` and `aclose()` is a connector.
- **Confirm before execute.** Matching tools gain a `confirmed` argument and refuse to run without it, and the prompt tells the model to read the action back first. This is model-mediated: it stops calls the model did not confirm, but it cannot hear the user say yes.
- **Background tools.** A matching tool returns "started" at once so the model keeps talking, and its result is sent into the session as a `[tool result]` message when it finishes.

## A minimal agent, without the facade

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

It learns a noise floor, so steady noise such as a fan raises the floor instead of holding a turn open. It uses separate start and end thresholds so a level near the edge does not flap, and it tolerates the short gaps between syllables. Time is measured in audio, not wall clock, so it is deterministic. Tune it with `EnergyTurnConfig` (for example `end_ms`).

For noisy rooms use the neural detector, a drop-in with the same protocol. It runs the bundled Silero VAD model on onnxruntime (no torch) and classifies the sound of speech instead of its loudness, so noise that would fool an energy threshold does not start a turn:

```python
from soro.audio import create_turn_detector

detector = create_turn_detector("silero")   # pip install "soro[vad]"
```

`python -m soro.evals turns` compares the detectors on the same noisy-room audio. On the built-in cases the energy detector false-triggers when a fan switches on mid-call and Silero does not.

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

## Local, free: the composed adapter

`ComposedLiveAdapter` builds the same `LiveSessionPort` from parts: a turn detector, speech to text, an LLM and text to speech. The defaults are local and need no API key: faster-whisper, any OpenAI-compatible server (Ollama, llama.cpp, vLLM) and a Piper voice.

```python
adapter = soro.create_live_adapter(
    "composed",
    composed_llm_base_url="http://localhost:11434/v1",   # Ollama
    composed_llm_model="qwen2.5",                         # pick a model trained for tool calls
    composed_tts_voice="voices/en_US-amy-medium.onnx",    # .onnx.json beside it
)
```

The adapter owns turn-taking (`native_vad=True`) with the Silero detector by default (`turn_detector="energy"` for the pure-Python one). Speech during a reply is a barge-in: the reply stops mid-sentence and `interrupted` is emitted. Replies are spoken sentence by sentence, so the first audio comes after the first sentence, not the whole reply. Any piece can be swapped by passing your own `SpeechToText`, `LanguageModel` or `TextToSpeech`; in-memory fakes of all three are in `soro.adapters.composed`. The LLM only sees text, so tone and hesitation are lost: that is the trade for running free and local. When a session opens, the adapter loads the Whisper and Piper models in the background (any component may define `async warm_up()`), so the first turn does not pay for the load.

### Measured on a laptop CPU

Run on 2026-10-05: 4 cores, no GPU, 8GB of RAM shared with an editor, llama.cpp's `llama-server --jinja`, Whisper `base.en` (int8) and Piper `en_US-lessac-medium`. `examples/local_voice_loop.py` speaks the caller's line with Piper and feeds it through the whole pipeline.

| LLM (Q4_K_M) | Spoken note, one tool call | `note_taker` (text) | `interview_order` (text, five ordered calls) |
|---|---|---|---|
| Qwen2.5 0.5B (470MB) | Pass. About 11s from the caller starting to the spoken confirmation | Fails: saves the note but does not greet | Fails: calls no tools |
| Qwen2.5 1.5B (1.1GB) | Not run | Pass. 19s to first audio, 10s per turn | Fails: invents the candidate's answers and writes later tool calls as text, which would be spoken |

What this means:

- The pipeline itself works: turn detection, transcription, tool round trips, sentence-by-sentence speech and history all behave as on the fakes.
- Small models are fine for simple single-tool assistants. Multi-step flows with ordering rules, such as the interview, need a larger model trained for tool calls (7B class, about 4.7GB at Q4), which in turn needs a machine with more free memory or a GPU.
- Whisper `base.en` transcribed 3.6s of speech in about 2.6s once loaded. On a CPU, the LLM is the slowest part, and its speed drops sharply when other programs compete for the cores.

To repeat the measurements: `python examples/local_voice_loop.py`, and `python -m soro.evals scenarios -p composed --turn-timeout 120 --session-timeout 300`.

## Evals

`soro.evals` measures a provider instead of guessing. A scenario is a scripted caller, the tools on offer, and what a good agent does (tool calls in order, with matching arguments, ordering rules, transcript patterns). The runner plays the caller against a real `VoiceAgentRuntime` on any adapter, records a timestamped trace, and scores time to first audio, turn latency, barge-in, tool-call correctness and reconnect recovery.

```bash
python -m soro.evals turns                           # noisy-room turn detection, energy vs silero
python -m soro.evals scenarios                       # the scripted baseline, no key needed
python -m soro.evals scenarios -p scripted,gemini    # add a real provider (reads GEMINI_API_KEY)
python -m soro.evals scenarios --list
```

`scenarios` exits non-zero when a run fails, so it can gate CI. Scenarios that need synthetic caller audio (barge-in, spoken turns, reconnects) run only on the scripted baseline; text scenarios run on every provider.

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
| `examples/connected_agent.py` | `Agent` with function and OpenAPI tools, confirm and background policy, no network or key |
| `examples/turn_detection.py` | The detector ignoring a fan and finding speech over it |
| `examples/local_voice_loop.py` | The free local pipeline end to end on real synthesized speech, scored by the eval harness (needs a local LLM server and a Piper voice) |

## Resilience

The Gemini adapter uses session resumption: a dropped connection, a transient server error, or Gemini's periodic connection recycle continues the same conversation. After a reconnect the adapter emits `session_resumed`, and the runtime sends your `resume_message` because the user's last turn may have been lost. `FallbackLiveAdapter` (what `create_live_adapter` returns when you pass a `fallback`) continues on the second provider if the first fails to open or fails before it produces any output.

## Configuration

Adapters take their settings as constructor arguments and fall back to the provider's usual environment variables (`GEMINI_API_KEY`, `GEMINI_LIVE_MODEL`, `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL`; for the composed adapter `SORO_LLM_BASE_URL`, `SORO_LLM_MODEL`, `SORO_LLM_API_KEY`, `SORO_LLM_TIMEOUT`, `SORO_STT_MODEL`, `SORO_PIPER_VOICE`). Soro reads no other global configuration.

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
