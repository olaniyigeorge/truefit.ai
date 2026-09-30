"""
Smoke test for an installed copy of soro. Run it in a clean virtualenv after
installing from TestPyPI or PyPI. It checks the package, not the source tree,
and needs no API key. Exits non-zero on the first failure.

    python scripts/smoke_test.py [--extras gemini,openai,webrtc]

With GEMINI_API_KEY or OPENAI_API_KEY set it also opens a real session.
"""

import argparse
import asyncio
import importlib
import importlib.metadata
import math
import os
import random
import sys
from array import array
from pathlib import Path


def step(name):
    print(f"ok  {name}")


def check_not_source_tree():
    import soro

    path = Path(soro.__file__).resolve()
    assert "site-packages" in path.parts, f"imported from {path}, not an installed copy"
    step(f"imported installed soro {importlib.metadata.version('soro')} from {path.parent}")


def check_public_api():
    import soro

    for name in soro.__all__:
        assert hasattr(soro, name), f"soro.{name} missing"
    assert (Path(soro.__file__).parent / "py.typed").exists(), "py.typed missing from the wheel"
    step("public API and py.typed present")


def check_core_needs_no_extras():
    # `pip install soro` alone must import and run the provider-free parts.
    from soro import ToolRegistry, ToolSpec  # noqa: F401
    from soro.audio import EnergyTurnDetector  # noqa: F401
    from soro.testing import FakeLiveAdapter  # noqa: F401

    step("core imports without extras")


async def check_runtime_with_fake_adapter():
    from soro import RuntimeCallbacks, SessionComplete, ToolRegistry, ToolSpec, VoiceAgentRuntime
    from soro.testing import FakeLiveAdapter

    seen = []

    async def note(args):
        seen.append(args["text"])
        return {"success": True}

    async def end(args):
        raise SessionComplete("done")

    async def mic():
        yield b"\x00\x00" * 320

    async def play(pcm):
        pass

    tools = (
        ToolRegistry()
        .register(ToolSpec(name="note", description="n", parameters={"type": "object", "properties": {"text": {"type": "string"}}}), note)
        .register(ToolSpec(name="end", description="e"), end)
    )
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "1", "name": "note", "args": {"text": "hi"}}), ("tool_call", {"id": "2", "name": "end", "args": {}})],
        hold_open_until_audio=1,
    )
    await asyncio.wait_for(
        VoiceAgentRuntime(
            adapter=adapter, system_prompt="p", tools=tools, audio_input_stream=mic(),
            callbacks=RuntimeCallbacks(on_audio_output=play),
        ).run(),
        timeout=10,
    )
    assert seen == ["hi"], seen
    step("runtime dispatches tool calls and ends on SessionComplete")


def check_turn_detection():
    from soro.audio import EnergyTurnDetector

    rng = random.Random(0)

    def chunk(rms):
        peak = rms * math.sqrt(3)
        return array("h", (int(rng.uniform(-peak, peak)) for _ in range(320))).tobytes()

    d = EnergyTurnDetector()
    fan = [d.process(chunk(900)) for _ in range(300)]
    assert not any(fan), "steady noise started a turn"
    events = [d.process(chunk(6000)) for _ in range(20)]
    assert any(e and e.kind == "start" for e in events), "speech over noise not detected"
    step("turn detection ignores steady noise and detects speech")


def check_factory_errors(extras):
    from soro import create_live_adapter

    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(var, None)
    try:
        create_live_adapter("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown provider did not raise ValueError")
    # With the extra: a clear missing-key error. Without it: a clear install hint.
    expected = RuntimeError if "gemini" in extras else ImportError
    try:
        create_live_adapter("gemini")
    except expected as exc:
        if expected is ImportError:
            assert 'soro[gemini]' in str(exc), exc
    else:
        raise AssertionError(f"create_live_adapter('gemini') did not raise {expected.__name__}")
    step("factory rejects unknown providers, and reports a missing key or extra clearly")


def check_extras(extras):
    modules = {
        "gemini": ["google.genai", "soro.adapters.gemini"],
        "openai": ["websockets", "soro.adapters.openai"],
        "webrtc": ["aiortc", "soro.transport.webrtc"],
    }
    for extra in extras:
        for mod in modules[extra]:
            importlib.import_module(mod)
        step(f"extra [{extra}] imports")
    if "webrtc" in extras:
        from soro.transport.webrtc import AudioBridge

        bridge = AudioBridge(session_id="smoke", output_sample_rate=24_000)
        assert bridge.create_outbound_track() is not None
        step("WebRTC AudioBridge builds an outbound track")


async def check_live():
    from soro import create_live_adapter

    provider = "gemini" if os.getenv("GEMINI_API_KEY") else "openai" if os.getenv("OPENAI_API_KEY") else None
    if not provider:
        print("skip live session (set GEMINI_API_KEY or OPENAI_API_KEY to run it)")
        return
    adapter = create_live_adapter(provider)
    async with adapter.open_session("Say hello in one short sentence.") as session:
        await session.send_client_content("Hello")
        async for event_type, _ in session.receive():
            if event_type in ("audio", "text", "turn_complete"):
                break
    step(f"live {provider} session opened and produced output")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--extras", default="", help="comma separated: gemini,openai,webrtc")
    extras = [e for e in parser.parse_args().extras.split(",") if e]
    check_not_source_tree()
    check_public_api()
    check_core_needs_no_extras()
    asyncio.run(check_runtime_with_fake_adapter())
    check_turn_detection()
    check_factory_errors(extras)
    check_extras(extras)
    asyncio.run(check_live())
    print("\nall smoke checks passed")


if __name__ == "__main__":
    sys.exit(main())
