# Build Plan: VAD, Connectors, Evals, Composed Adapter

**Status:** All four steps built (2026-10-03). See "Outcome" at the end for results and where the build departed from the plan.
**Date:** 2026-10-03
**Companion to:** [voice-infra-pivot.md](./voice-infra-pivot.md) (the strategic assessment and progress log)

This doc is the tactical plan for the next four items in the pivot's near-term order. The
pivot doc says *what* and *why*; this one says *how*, file by file, in the order the work lands.

## Context

TrueFit.ai has finished the hard part of its pivot: a clean `LiveSessionPort`, an extracted
`VoiceAgentRuntime`, Gemini + OpenAI adapters, a fallback wrapper, and a pluggable energy turn
detector all live in the `soro` package ([packages/soro](../packages/soro)), with a green suite
(183 passed, 2 skipped). The next four items turn Soro from "two paid speech-to-speech providers"
into real model-agnostic infrastructure:

1. A **neural turn detector** plus a repeatable **noisy-room scenario**, so end-of-turn quality is
   measured, not guessed (the fan-noise bug is only partly closed today).
2. A **connector layer** (functions, then OpenAPI, then MCP). This is the differentiator: it lets
   someone point Soro at an existing system and talk to it, instead of hand-writing every
   `ToolSpec` and handler.
3. An **eval harness** inside the package, so swapping providers or editing a prompt or adapter is
   measured (latency, tool-call correctness, barge-in) rather than hoped.
4. A **ComposedLiveAdapter** (STT, LLM, TTS behind the port), the free/open path, so
   "model-agnostic" includes open models and not just two cloud APIs.

The work is additive to the SDK and to the interview app (the reference consumer); no existing
public seam changes shape. Everything new follows the package's established conventions: a Protocol
with a concrete default, lazy provider imports behind optional extras, in-memory fakes for CI, and
tests that mirror source files.

## Decisions

- **Neural VAD:** Silero via `onnxruntime` (no torch). New optional extra `soro[vad]`. The ONNX
  model is bundled in the package (MIT licensed) so detection is offline and deterministic.
- **Composed backend:** fully local, no API keys. faster-whisper (STT) + Piper (TTS) + an
  OpenAI-compatible local LLM endpoint (Ollama or a llama.cpp server, reached by `base_url`, no key).
- **Testability rule (applies to items 1 and 4):** every concrete provider sits behind a Protocol
  with an in-memory fake. CI runs on fakes; real-model tests skip when the dependency or model is
  absent, exactly like the existing provider tests.

## Build sequence

Dependency-ordered. Each step lands with the full suite green and docs updated before the next
begins.

### Step 1: Neural turn detector + noisy-room scenario

Add `SileroTurnDetector` implementing the existing `TurnDetector` protocol
([turn.py](../packages/soro/src/soro/audio/turn.py)) so it is a drop-in for `EnergyTurnDetector`.
Silero gives a per-frame speech probability; wrap it in the same start/end hangover state machine
(`start_ms` / `end_ms`), buffer arbitrary PCM into the model's 512-sample (32ms at 16kHz) frames,
and keep `advance_silence` / `reset` / `is_speaking` semantics identical so `AudioBridge` and the
runtime treat the two detectors the same. `AudioBridge` already accepts a `turn_detector=` argument
([webrtc.py](../packages/soro/src/soro/transport/webrtc.py)), so no bridge change is needed beyond
allowing the neural detector to be selected.

- New: `src/soro/audio/silero.py` (`SileroTurnDetector`, `SileroTurnConfig`).
- New: `src/soro/audio/assets/silero_vad.onnx`, the bundled model, loaded via `importlib.resources`
  and packaged through a hatch force-include in `pyproject.toml`.
- Edit: `audio/turn.py` `create_turn_detector()` gains a `"silero"` case (lazy import, a clear
  "install soro[vad]" error that mirrors `factory._missing_extra`).
- Edit: `audio/__init__.py` exports the new names.
- Noisy-room scenario: create the evals package skeleton `soro/evals/` now, with a focused
  turn-detection eval `soro/evals/turn_detection.py`. Reuse the synthetic audio generators already
  proven in [test_turn_detection.py](../packages/soro/tests/test_turn_detection.py) (speech, fan,
  speech-over-fan, mid-call fan), score detection accuracy, false triggers, and end-of-turn latency,
  and tabulate energy vs silero side by side. Step 3 extends this package.
- Tests: `tests/test_silero_detector.py` (skips if `onnxruntime` is missing); add silero to the
  protocol and factory assertions; `tests/test_evals_turn_detection.py` for the scorer on fixtures.
- Deps: `vad = ["onnxruntime>=1.17", "numpy>=1.24"]`.

### Step 2: Connector layer + Agent facade

A connector is anything that produces `(ToolSpec, handler)` pairs to feed a `ToolRegistry`
([registry.py](../packages/soro/src/soro/runtime/registry.py)); the registry and runtime are
unchanged. Add a thin `soro.Agent` facade that composes connectors, prompt, and policy into a
`VoiceAgentRuntime`, matching the target developer experience in the pivot doc.

- New package `soro/connectors/`:
  - `base.py`: a `Connector` protocol (`async tools() -> list[(ToolSpec, ToolHandler)]`, `async aclose()`).
  - `functions.py`: a `@tool` decorator and a `functions(*fns)` connector that introspects signature,
    type hints, and docstring into a `ToolSpec` (JSON Schema) and wraps sync or async callables as
    handlers. This is the minimal first cut and the base the others reuse.
  - `openapi.py`: parse an OpenAPI 3 spec (JSON or YAML) into one `ToolSpec` per operation
    (`operationId`, summary, parameter and requestBody schema); the handler issues the HTTP call with
    `httpx`, mapping args to path, query, and body, with a `base_url`, auth, and an operation or tag
    allowlist. Extra `soro[openapi]`.
  - `mcp.py`: connect to an MCP server (stdio or HTTP) via the `mcp` SDK, `list_tools` into
    `ToolSpec`s, and proxy `call_tool` from the handler. Lazy import, extra `soro[mcp]`.
- Response policy (the voice-specific needs from the pivot doc), in `soro/runtime/policy.py`, applied
  by the Agent facade rather than baked into `VoiceAgentRuntime`:
  - Non-blocking tools: a slow tool runs as a background task; the handler returns an immediate ack
    so the model can keep talking, and the real result is injected via `send_client_content` on
    completion. Concrete and unit-testable.
  - Confirm-before-execute: `confirm=["schedule_meet", "delete_*"]` wraps matching handlers to require
    verbal confirmation (a guard plus a system-prompt convention). Best-effort, documented as
    model-mediated.
  - Listen-only / ambient mode is a small follow-on, not built here, to avoid overreach.
- New: `soro/agent.py`, with `Agent(prompt=, connectors=, confirm=, adapter= or provider=, ...)` and
  `await agent.run(audio_input_stream=, on_audio_output=, ...)`. It builds the registry from
  connectors, applies policy, constructs `VoiceAgentRuntime`, and `aclose()`s connectors on exit.
- Edit: `soro/__init__.py` exports `Agent`, `tool`, and a `connectors` namespace.
- Tests: one file per connector (functions, openapi, mcp, the last two using a local stub server and
  a fake MCP server so no network is needed), `test_policy.py`, and `test_agent.py` end to end on
  `FakeLiveAdapter`.
- New example: `examples/connected_agent.py`.

### Step 3: Eval harness

Extend `soro/evals/` from step 1 with scenario-based adapter and agent evals that run through any
`LiveSessionPort`. Deterministic CI runs use a scripted adapter (a `FakeLiveAdapter` subclass that
emits events per script); live per-provider runs are opt-in and need keys.

- New in `soro/evals/`:
  - `scenario.py`: a `Scenario` (scripted caller turns, expected tool calls, args, and order, and
    expected transcript patterns) and a `ScenarioRunner` driving a `VoiceAgentRuntime`.
  - `scripted_adapter.py`: the deterministic adapter for cheap runs.
  - `metrics.py`: time-to-first-audio, per-turn latency, barge-in handling, tool-call correctness
    (right tool, right args, right order, for example never advancing before `persist_answer`),
    reconnect recovery, and a cost-per-session placeholder.
  - `report.py`: a `Scorecard` dataclass and a plain-text table; `__main__.py` provides a
    `python -m soro.evals` CLI for per-provider comparison across a scenario set.
- Reuse the turn-detection eval from step 1 as the noisy-room end-of-turn dimension.
- Tests: `test_evals_scenarios.py`, `test_evals_metrics.py` on the scripted adapter.
- Deps: none new (stdlib and existing).

### Step 4: ComposedLiveAdapter

One adapter implementing `LiveSessionPort` that hides a VAD, STT, LLM, TTS pipeline and emits the
same normalised events, mirroring the `open_session` and `receive` shape of
[openai.py](../packages/soro/src/soro/adapters/openai.py). It owns turn-taking with a `TurnDetector`
(reusing step 1), so to the runtime `native_vad=True`; `output_sample_rate` reflects the configured
TTS (Piper is commonly 22.05kHz) and is read from `capabilities`, which the port already supports.

- New package `soro/adapters/composed/`:
  - `components.py`: `SpeechToText`, `LanguageModel`, `TextToSpeech` protocols plus in-memory fakes.
  - `adapter.py`: `ComposedLiveAdapter`. It buffers mic audio and runs the detector; on end-of-turn
    it transcribes the utterance (emit `input_text`), streams the LLM with history and tools (emit
    `tool_call`, await `send_tool_response`, continue), pipes LLM text sentence by sentence to TTS
    (emit `audio`), then `turn_complete`; on barge-in it emits `interrupted` and cancels the
    in-flight LLM and TTS. It constructs without network (components are injected), so it joins the
    contract suite like the others.
  - `faster_whisper_stt.py`, `piper_tts.py`, `openai_compat_llm.py`: the local backends, lazily
    imported; `openai_compat_llm.py` streams chat completions from a local `base_url` with no key.
  - `__init__.py`: `create_composed_adapter(...)` wiring the local defaults.
- Edit: `adapters/factory.py` adds `"composed"` to `PROVIDERS` and a `_make_adapter` case that
  delegates to `create_composed_adapter`.
- Edit: `tests/test_adapter_contract.py` adds a `_composed()` built from fakes to `ADAPTERS`.
- Tests: `tests/test_composed_adapter.py` drives the whole event flow on fake components (speech in,
  then `input_text`, `tool_call`, audio out, `turn_complete`, plus a barge-in case). Backend wrappers
  get thin tests that skip without the model or server.
- Deps: `composed = ["faster-whisper>=1.0", "piper-tts>=1.2", "httpx>=0.27"]`. The `all` extra is
  extended to include `vad` and `composed`.

## pyproject extras

Added to [packages/soro/pyproject.toml](../packages/soro/pyproject.toml):

```
vad      = ["onnxruntime>=1.17", "numpy>=1.24"]
openapi  = ["httpx>=0.27", "pyyaml>=6"]
mcp      = ["mcp>=1.0"]
composed = ["faster-whisper>=1.0", "piper-tts>=1.2", "httpx>=0.27"]
all      = ["soro[gemini,openai,webrtc,vad,composed]"]
```

Plus a hatch force-include for the bundled `silero_vad.onnx`.

## Conventions to hold

- `from __future__ import annotations`; docstrings that explain the why; frozen dataclasses for
  config and value types; Protocols for the pluggable seams; lazy imports with an "install soro[x]"
  message for every optional dependency; no global config read inside the SDK.
- The core never imports a provider SDK; all SDK types stay inside their adapter or component module.
- Tests mirror source files and run without network; provider and model tests skip when the
  dependency is absent, as the two currently-skipped tests do.

## Verification

Run after each step and at the end:

```bash
# SDK suite (fakes only; must stay green)
examples/truefit/backend/.venv/bin/python -m pytest packages/soro/tests -q

# with the new optional deps installed, to exercise the silero and composed wrappers
examples/truefit/backend/.venv/bin/pip install -e "packages/soro[dev,vad]"
examples/truefit/backend/.venv/bin/python -m pytest packages/soro/tests -q

# examples still run with no network or key
examples/truefit/backend/.venv/bin/python packages/soro/examples/offline_note_taker.py
examples/truefit/backend/.venv/bin/python packages/soro/examples/connected_agent.py

# eval CLI on the scripted adapter and the noisy-room turn-detection scenario
examples/truefit/backend/.venv/bin/python -m soro.evals --help

# the interview app (reference consumer) still passes
cd examples/truefit/backend && .venv/bin/python -m pytest tests -q
```

Beyond CI: run the connected agent example against a real adapter, and run the eval CLI's
per-provider comparison. Live composed-path runs need a local LLM endpoint plus the Piper and
whisper models and are documented as opt-in, not part of CI.

## Out of scope and follow-ups

- Live validation of the composed path against downloaded models and a running local LLM.
- Full ambient / listen-only mode and MCP resource (non-tool) support.
- Hosted HTTP API and client SDKs (separate roadmap items). The interview app has since moved to `examples/truefit/` on `main` rather than a separate branch.

## Outcome (2026-10-03)

All four steps are built. The Soro suite is at 282 passed, 4 skipped (up from 183 passed, 2 skipped), and the interview app suite still passes (353). The two new skips are the real faster-whisper and Piper tests, which need model files (`SORO_TEST_WHISPER_MODEL`, `SORO_TEST_PIPER_VOICE`). `import soro` still loads no optional dependency.

What the evals show today:

- **Noisy room** (`python -m soro.evals turns`): the energy detector false-triggers when a fan switches on mid-call (`fan_switches_on`); Silero passes every case. Silero is not scored on the synthetic "speech" cases because they are only an energy envelope, not real speech; real recordings dropped in via `load_wav_frames` are the way to measure its true-positive latency.
- **Scenarios** (`python -m soro.evals scenarios`): all five built-in scenarios pass on the scripted baseline. The composed adapter on fake components passes the same harness.

Where the build departed from the plan:

- **`evals/trace.py`** is new: a `TracingAdapter` that wraps any adapter and timestamps every event in both directions. All metrics read the trace, never the provider, which is what makes numbers comparable across providers. Trace ordering uses event positions rather than timestamps, since two events can share a rounded time.
- **`Agent`** also takes `background=` (non-blocking tool patterns) and `tools=` (shorthand for `connectors.functions(...)`).
- **Composed `send_client_content`** queues behind a reply in progress instead of interrupting it, so a background tool result never cuts the agent off mid-sentence. Only spoken barge-in interrupts.
- **Composed configuration** falls back to `SORO_LLM_BASE_URL`, `SORO_LLM_MODEL`, `SORO_LLM_API_KEY`, `SORO_STT_MODEL` and `SORO_PIPER_VOICE`, mirroring how the cloud adapters fall back to their key variables. The factory gained `composed_*` arguments.
- **The contract suite** now allows a 22.05kHz output rate (Piper's usual rate).
- **MCP SDK 2.x** renamed fields (`input_schema`, `is_error`, `structured_content`) and `FastMCP`; the connector reads both spellings, and its real stdio test runs against 2.3.
- **Packaging:** the model is listed under hatch `artifacts` (not `force-include`), with an `assets/__init__.py` so `importlib.resources` finds it. `composed` also lists `numpy`, and `all` includes `openapi` and `mcp` too. Because `dev` pulls `all`, `pip install -e ".[dev]"` now installs faster-whisper and Piper; split `dev` if that is too heavy.
- **`python -m soro.evals turns`** is a comparison, not a gate: it exits 0 even though the energy detector fails `fan_switches_on`, because showing that is its job. `scenarios` is the CI gate.

Still open: live validation of the composed path (a running LLM server plus downloaded Whisper and Piper models), switching the interview app's `AudioBridge` to Silero, listen-only mode, and MCP resources.

