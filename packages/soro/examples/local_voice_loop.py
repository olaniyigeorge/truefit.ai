"""
The free local pipeline, end to end, with no microphone: Piper speaks the
caller's lines, and the composed adapter hears them through turn detection and
Whisper, answers with a local LLM (calling a tool), and speaks back with Piper.
The eval harness scores the run, so the timings printed are the same metrics
`python -m soro.evals` reports for any provider.

Needs pip install "soro[composed,vad]", an OpenAI-compatible LLM server and a
Piper voice. For example, with llama.cpp:

    llama-server -m qwen2.5-1.5b-instruct-q4_k_m.gguf --jinja --port 8080
    export SORO_LLM_BASE_URL=http://127.0.0.1:8080/v1
    export SORO_PIPER_VOICE=/path/to/en_US-lessac-medium.onnx
    python examples/local_voice_loop.py

Whisper downloads its model (SORO_STT_MODEL, default base.en) on first use.
"""

import asyncio
import os
import re

from soro.adapters.composed import create_composed_adapter
from soro.adapters.composed.piper_tts import PiperTTS
from soro.audio.resampler import PcmResampler
from soro.evals import (
    CallerTurn,
    ExpectedCall,
    Scenario,
    ScenarioRunner,
    format_scorecards,
    scorecard,
)
from soro.tools import ToolSpec

CALLER_LINES = ["Hello. Please save a note that says buy milk."]
FRAME_BYTES = 640  # 20ms of 16kHz s16 mono, what a browser mic delivers
TRAILING_SILENCE = 50  # 1 second, so the turn detector sees the caller stop


async def speak(tts: PiperTTS, text: str) -> tuple[bytes, ...]:
    """Synthesize a caller line and cut it into 16kHz mic frames."""
    resampler = PcmResampler(tts.sample_rate, 16_000)
    pcm = b"".join([resampler.process(chunk) async for chunk in tts.synthesize(text)])
    pcm += b"\x00" * (-len(pcm) % FRAME_BYTES)
    frames = [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    return tuple(frames + [b"\x00" * FRAME_BYTES] * TRAILING_SILENCE)


async def main() -> None:
    voice = os.environ.get("SORO_PIPER_VOICE")
    if not voice:
        raise SystemExit("Set SORO_PIPER_VOICE to a Piper voice .onnx file")

    caller = PiperTTS(voice)
    turns = tuple([CallerTurn(audio=await speak(caller, line)) for line in CALLER_LINES])
    scenario = Scenario(
        name="local_voice_loop",
        prompt="You are a friendly note-taking assistant on a phone call. Keep every reply to one short sentence. "
        "When the user asks you to remember something, call save_note with it, then confirm.",
        turns=turns,
        tools=(
            ToolSpec(
                "save_note",
                "Save a note for the user.",
                {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
        ),
        expected_calls=(ExpectedCall("save_note", {"text": re.compile("milk", re.I)}),),
    )

    adapter = create_composed_adapter()  # Silero turn detection by default
    # A small model on a laptop CPU can take tens of seconds per reply.
    run = await ScenarioRunner(turn_timeout_s=180, session_timeout_s=600).run(
        scenario, adapter, "composed"
    )

    for event in run.trace.events:
        if event.kind in ("input_text", "text", "tool_call"):
            print(f"{event.t:6.1f}s  {event.kind:<10} {event.data}")
    print()
    print(format_scorecards([scorecard(run)]))


asyncio.run(main())
