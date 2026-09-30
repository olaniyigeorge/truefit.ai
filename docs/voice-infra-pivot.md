# Pivot Review: Interview Product → Model-Agnostic Voice Infrastructure

**Status:** Assessment — informs the pivot decided 2026-09-28
**Date:** 2026-09-29
**Scope:** What it would actually take to turn TrueFit.ai from an AI-interview product into reusable, model-agnostic infrastructure for voice agents (interviews, meetings, conversational, note-taking, and other applications built on top).

> This review is based on reading the code on `main`, not the README (which is partly aspirational). File references link to the real source.

---

## Headline

The pivot is **much less green-field than it looks**, but the hardest part of it is **bigger than the working notes suggest**. Two findings drive everything below:

1. **The core seam is real and well-designed.** [`LiveSessionPort`](../apps/backend/src/truefit_core/application/ports.py#L392) is a genuine hexagonal port — normalized `(event_type, data)` event tuples, an explicit audio-format contract, and abstracted tool-calling. It is not decoration. [`GeminiLiveAdapter`](../apps/backend/src/truefit_infra/llm/gemini_live.py) really is the only file that imports the Google GenAI SDK.

2. **Multi-provider support was already built — and never merged.** Commits `f0ed618`, `13502f0`, and `5147d52` (on branches `dev` and `open-ai-rt`) contain a complete `OpenAIRealtimeAdapter`, a `LiveAdapterFactory` (env-driven provider selection), and a `FallbackLiveAdapter`, all implementing `LiveSessionPort` cleanly. **None of it is on `main`.** That is why the working tree carries orphaned `openai_realtime.pyc` / `factory.pyc` / `fallback_adapter.pyc` under `llm/__pycache__/` with no matching source.

The practical meaning of finding 2: **the abstraction has already been proven against two independent providers.** Proving a second implementation is the hardest validation an infra seam gets, and it is done. What remains is (a) recovering that work, (b) removing coupling in the layers *above* the port, and (c) the one genuinely large build — the free/open-model path.

---

## What was in the repo before the pivot work (snapshot)

> Historical. This table describes the code as it was when this review was written. The current layout is in [The Soro package](#the-soro-package) below.

| Layer | File | State |
|---|---|---|
| Port (abstraction) | [`application/ports.py`](../apps/backend/src/truefit_core/application/ports.py#L392) | Real, clean, provider-neutral event contract |
| Gemini adapter | [`llm/gemini_live.py`](../apps/backend/src/truefit_infra/llm/gemini_live.py) | Complete; SDK isolation holds |
| OpenAI adapter | `llm/openai_realtime.py` (branch `dev`) | Complete, **unmerged** |
| Provider factory | `llm/factory.py` (branch `dev`) | Complete, **unmerged** |
| Fallback wrapper | `llm/fallback_adapter.py` (branch `dev`) | Complete, **unmerged** |
| Voice agent loop | [`agents/interviewer/live_interview_agent.py`](../apps/backend/src/truefit_core/agents/interviewer/live_interview_agent.py) | Works, but coupled to the interview domain (see Gap 1) |
| Tool declarations | [`agents/interviewer/tools.py`](../apps/backend/src/truefit_core/agents/interviewer/tools.py) | Interview-specific, baked into the agent |
| WS wiring | [`api/v1/ws/interview_websocket.py`](../apps/backend/src/truefit_api/api/v1/ws/interview_websocket.py#L96) | Hardcodes `GeminiLiveAdapter()` instead of the factory |
| Config | [`infra/config.py`](../apps/backend/src/truefit_infra/config.py) | Has `GEMINI_*` keys; **no** `LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` yet |

**Audio contract** (relied on across layers): inbound 16kHz mono s16 PCM, outbound 24kHz mono s16 PCM, with the WebRTC `AudioBridge` resampling to/from 48kHz Opus at the browser edge.

---

## Progress (updated 2026-09-29)

| Item | Status |
|---|---|
| Step 1: recover multi-provider code, factory in WS layer | Done |
| Gap 1: `VoiceAgentRuntime` extraction | Done |
| Gap 2: tighten the port (capabilities, neutral tools and events) | Done |
| Extract the SDK into `packages/soro` (step 5, first half) | Done (app imports it, both suites green) |
| Pluggable turn detection (fixes the fan-noise bug) | Done (`soro.audio.EnergyTurnDetector`, `AudioBridge` uses it; neural detector and a noisy-room eval scenario still open) |
| Connector layer (turn an existing system into tools) | Not started |
| Non-blocking tools and a response policy (listen-only, addressed) | Not started |
| Eval harness (one pipeline, both approaches) | Not started |
| Step 4: `ComposedLiveAdapter` (Gap 3) | Not started, research done |
| Hosted HTTP API and client SDKs | Not started |
| Step 3: use cases on the `truefit` branch (interview, personal OS, meeting copilot) | Interview exists; the rest not started |

Also fixed while getting a clean baseline: `Candidate.attach_resume()` (callers never passed the asset id), `JobService.create_job()` / `CreateJobCommand` (out of sync with the `Job` aggregate, now take `created_by` and `requirements`), and a test helper that turned `skills=[]` into default skills. The Soro package suite has 162 passing tests and the interview app suite 181, apart from one old script (`tests/test_auth.py`) that was already failing.

**What Gap 1 delivered**

- `VoiceAgentRuntime` (`agents/runtime/runtime.py`) depends only on `LiveSessionPort`. Prompt, tools, opening message, I/O callbacks and an `on_error` hook are inputs. Ending a session is a generic `SessionComplete` exception or `runtime.stop()`.
- `ToolRegistry` (`agents/runtime/tools.py`) holds declaration and handler together and rejects mismatches at construction.
- `LiveInterviewAgent` is now a thin consumer. Its tool handlers moved to `agents/interviewer/handlers.py`. It is typed against `LiveSessionPort` and imports nothing from `truefit_infra`.
- Behaviour change: when either loop ends (model closes the stream, mic closes, `go_away`), the other is cancelled. Before, `gather()` could leave the mic loop hanging.
- Isolation is tested: the runtime is exercised with a non-interview tool set, and a test fails if the runtime imports infra, services, domain or interviewer code.

`application/ports.py` used to import the ORM models from `truefit_infra`. It now uses the domain `User` and `Application`, and a test fails if anything under `truefit_core` imports infra, api or workers.

**What Gap 2 delivered**

- `AdapterCapabilities` on the port: `input_sample_rate`, `output_sample_rate`, `supports_images`, `native_vad`. Gemini and OpenAI declare 16kHz in, 24kHz out. The audio bridge, WebRTC client and signaling now take the output rate from the adapter instead of assuming 24kHz, and the WebSocket layer refuses an adapter whose input rate the bridge cannot deliver.
- `ToolSpec` (`application/tools.py`): a provider-neutral tool description. `ToolRegistry` and the runtime use it, and each adapter translates it (`_to_gemini_tools`, `_to_openai_tools`). `normalize_tools` still accepts the legacy Gemini group shape, so `INTERVIEW_TOOLS` works unchanged.
- `send_image` is an optional capability. The default raises `CapabilityNotSupported`, so a frame is never silently dropped.
- `go_away` became the neutral `session_ending` event with a reason payload. The valid event set is `LIVE_EVENT_TYPES`.
- Manual turn signalling (`send_activity_start`, `send_activity_end`, `send_audio_stream_end`) is now on the port as optional methods.
- `FallbackLiveAdapter` merges its two adapters' capabilities and refuses at construction if their sample rates or `native_vad` disagree.
- A shared contract suite (`tests/unit/llm/test_adapter_contract.py`) runs against the fake, the fallback wrapper and both real adapters. A composed adapter should be added to it when it exists.

Real bugs found and fixed on the way:

- The OpenAI adapter received the interview tools in Gemini's group shape and passed them through untouched, so it would never have registered a usable tool. This matches the caveat already noted in `docs/doc.md`.
- The WebSocket layer called `send_activity_start()` and `send_activity_end()` on the adapter, but `FallbackLiveAdapter` had neither, so any fallback configuration would have raised `AttributeError` at the first turn boundary.

- The OpenAI adapter still spoke the retired Realtime beta protocol, and OpenAI now answers `beta_api_shape_disabled`. It is migrated to GA (no beta header, `session.type: realtime`, `output_modalities`, nested `audio.input` / `audio.output`, renamed transcript events), verified against the field definitions in OpenAI's official Python SDK. GA only accepts 24kHz PCM, so the adapter now upsamples the bridge's 16kHz itself. The old code labelled 16kHz audio as `pcm16` (24kHz), so OpenAI would have heard the candidate 1.5x too fast.
- `response.done` with status `incomplete` (token limit, content filter) produced no event, which would have left the agent waiting forever. It now ends the turn.
- The fallback did not engage when the primary opened and then failed on its first event, which is exactly what the beta shutdown looked like. It now fails over when the primary fails before producing output and replays the opening message. Failures after output has started still propagate.
- The Gemini adapter read the SDK's `session.receive()` once, and the SDK ends that call after every model turn. The agent greeted the candidate and then never answered again, with the mic left open. The adapter now keeps reading across turns until the session closes, and the port documents that `receive()` spans the whole session. The WebSocket layer also reports an error to the UI if the agent's session ends without a deliberate completion, instead of leaving a live mic with no agent.
- Gemini closed sessions with `1011 Internal error occurred`, once before any audio and once right after the candidate finished a long answer (the model is a preview one, and Google gives no reason). Every such close ended the interview. The Gemini adapter now enables session resumption and reconnects on transient close codes (1001, 1006, 1011, 1012, 1013). With a resume handle the conversation continues server-side. With none yet (an early failure) it restarts and replays the opening message. `go_away`, the server's periodic connection recycle, now resumes instead of ending the session, which any interview past about ten minutes needs. Context-window compression is on too, because audio sessions are otherwise capped near 15 minutes. After a reconnect the adapter emits a `session_resumed` event, and the runtime sends the consumer's `resume_message` (for interviews: apologise and ask the candidate to repeat their last answer, since the last turn may have been lost). Three failed reconnects in a row end the session. The Live model can be overridden with `GEMINI_LIVE_MODEL`.
- `OpenAIRealtimeAdapter.is_healthy()` read `ws.open`, which `websockets` 16 removed, so it would have raised `AttributeError`.

Behaviour note: OpenAI no longer accepts and drops images silently. It reports `supports_images=False` and raises if asked.

## The Soro package

Decided 2026-09-29: the infrastructure is an installable Python SDK called **Soro** (`packages/soro`), offered later over HTTP as well so web and mobile apps can reach it. The idea is voice as an interface layer: install the SDK, connect it to an existing system, and that system becomes something you can talk to. Use cases are built on top by other people, not shipped by us.

```
packages/soro/            the SDK. Depends on no app.
  src/soro/
    ports.py              LiveSessionPort, AdapterCapabilities, event vocabulary
    tools.py              ToolSpec, normalize_tools
    runtime/              VoiceAgentRuntime, ToolRegistry
    adapters/             gemini, openai, fallback, factory (explicit config, no globals)
    audio/                PcmResampler
    testing.py            FakeLiveAdapter for consumers' own tests
  tests/                  unit and contract tests, no interview code
apps/                     the interview app: a reference consumer of Soro
```

- Installed as `soro[gemini]`, `soro[openai]` or `soro[all]`. The backend's `requirements.txt` installs it from `../../packages/soro`, so `pip install -r` must run from `apps/backend` (the `Makefile`, `scripts/dev.sh` and `scripts/deploy.sh` all do).
- Adapters take config as constructor arguments and fall back to the provider's usual environment variables. Soro reads no other global configuration.
- Version 0.1.0, alpha. The port may still change while the composed approach is validated against it. Do not publish until then.

Testing has three levels, none of which needs the interview app: automated unit and contract tests in the package, live smoke tests through a small example agent, and the interview app as the end-to-end consumer.

## The layers, and what is missing

| Layer | State |
|---|---|
| Models: one port over Gemini Live, OpenAI Realtime, later a composed pipeline | Built |
| Runtime: loops, tool dispatch, lifecycle, reconnect recovery | Built |
| Connectors: turn an existing system into tools (functions, OpenAPI, MCP) | Missing |
| Turn detection | Pluggable energy detector with adaptive noise floor; neural option open |
| Transport: WebRTC and WebSocket, client SDKs | Inside the interview app |
| Hosted API: sessions, keys, tenants | Not started |
| Evals | Not started |

The connector layer is what delivers the idea above, and it is where Soro can differ from runtime and transport frameworks. Voice adds requirements a text agent does not have: confirm risky actions aloud, summarise tool results for the ear, keep talking while a slow tool runs, permissions and an audit log, and an ambient mode that listens and speaks only when addressed.

Target developer experience (not built yet):

```python
agent = soro.Agent(
    prompt="You are my assistant. You can read my notes and manage my calendar.",
    connectors=[soro.connectors.openapi("https://my-os.example/openapi.json"),
                soro.connectors.mcp("google-calendar")],
    confirm=["schedule_meet", "delete_*"],
)
```

## The two approaches

The port is meant to hold two approaches. The **speech-to-speech** approach (Gemini Live, OpenAI Realtime) hears the audio directly. The **composed** approach (streaming STT, an LLM, streaming TTS) works with text in the middle, so it cannot perceive emotion, hesitation or timing the way a native audio model can. That limit is built into the design: adapters declare it as a capability, and the composed adapter mitigates it by keeping filler words and passing word timings and confidence through, with an optional prosody step. It is an approximation and the docs should say so.

Research on the free path (2026-09-29, unverified beyond the sources): OpenRouter's free `deepgram/flux-tts` is a whole-file HTTP call limited to 50 requests per day, with undocumented streaming, so it suits a fallback, not a live path. The live path would be Deepgram streaming STT (Flux, with end-of-turn detection) and streaming TTS, with new accounts getting $200 of credit.

## Known issues

- **Gemini `1011 Internal error occurred`.** The Live model `gemini-2.5-flash-native-audio-preview-12-2025` closes sessions with 1011, often 4 to 10 seconds in while generating the first response. Google documents no cause. Forum reports describe the same model failing very frequently since late May 2026, including with session resumption on, so this looks like preview-model instability, not our bug. The adapter reconnects on transient close codes and gives up after three failed reconnects in a row (a reconnect only counts as good once a turn completes). Options: set `GEMINI_LIVE_MODEL` to a newer model (Google's models page lists `gemini-3.8-live` as GA, unverified here, and the 3.x models differ in tool and turn behaviour, so the adapter config may need per-model changes), or send the first text turn with `send_realtime_input` (an untested suggestion).
- **Fan noise keeps the mic "speaking".** `AudioBridge` ends a turn with a hand-rolled detector: any chunk whose peak exceeds 400 counts as speech and resets the 0.8 second silence timer, so steady noise never lets a turn end. `SILENCE_THRESHOLD` is defined and unused, so there is no hysteresis, and only the first 32 samples of each 20ms chunk are inspected. The fix is pluggable turn detection in the SDK (an adaptive energy detector, an optional neural detector such as Silero, or the provider's own) plus a noisy-room eval scenario.
- **OpenAI path unverified live.** The GA migration is unit-tested against the SDK's field definitions but has not run against the real API because the account's credit is exhausted.
- **Deploy will need a branch switch.** `scripts/deploy.sh` pulls `main`. When `apps/` moves to the `truefit` branch, deployment must follow it.

## Near-term order

1. Pluggable turn detection, which also fixes the fan bug.
2. Connector layer, minimal first: decorated functions and non-blocking tools, then MCP and OpenAPI import.
3. Eval harness inside the package: time to first audio, turn latency, barge-in, tool round trip, reconnects, noisy-room end-of-turn, run per approach.
4. Composed adapter, validated against the port, then publish 0.1.
5. Cut the `truefit` branch with the interview app, then build the personal OS assistant and meeting copilot as outside consumers.

## The gaps

### Gap 1 — Coupling leaks above the port (blocks "others can build on it")

The port is clean; the layers above it are not yet reusable.

- [`LiveInterviewAgent`](../apps/backend/src/truefit_core/agents/interviewer/live_interview_agent.py#L18) imports the **concrete** `GeminiLiveAdapter` and type-hints against it (lines 18, 93) rather than `LiveSessionPort`. It also hard-imports `INTERVIEW_TOOLS`, `build_system_prompt`, `InterviewContext`, and `InterviewOrchestrationService`. The "agent" *is* the interview product — it is not a reusable voice-agent runtime.
- The WebSocket layer [hardcodes `GeminiLiveAdapter()`](../apps/backend/src/truefit_api/api/v1/ws/interview_websocket.py#L96) in `get_gemini_live()`; it should resolve through the factory.
- The [tools](../apps/backend/src/truefit_core/agents/interviewer/tools.py) (`record_question`, `persist_answer`, `complete_interview`, `flag_interrupt`) are interview-domain concepts hard-wired into the agent's dispatcher.

**What it takes:** extract a domain-neutral `VoiceAgentRuntime` — the two-loop send/receive engine plus tool dispatch — that depends only on `LiveSessionPort` and takes tools, system prompt, and tool-handlers as *inputs*. The interview becomes the first *consumer* of the runtime, not the runtime itself. This is a refactor, not a rewrite: the callback seam (`on_audio_output`, `on_text_output`, `on_interrupt`, `on_turn_complete`) already exists.

### Gap 2 — Gemini's shape leaks into the port

**Resolved** (see Progress above). `LiveSessionPort` assumed the provider owns the whole realtime loop, documented output sample rate as "Gemini Live returns 24kHz", and carried Gemini-isms (`send_image`, `go_away`, Gemini-shaped tools). It now declares capabilities and sample rates, uses neutral tools and events, and makes images and manual turn signalling optional.

### Gap 3 — Every layer assumes a single realtime *speech-to-speech* API (the big one)

This is the gap the working notes do not address, and it is what decides whether the pivot is "weeks" or "a couple of months."

The whole stack assumes one WebSocket that natively does STT + LLM + TTS + VAD + tool-calling (Gemini Live, OpenAI Realtime). **Free/open models do not work this way.** There is no reliable *free* hosted speech-to-speech realtime API. The open path is a **composed pipeline**:

```
mic → VAD → STT (e.g. Whisper / faster-whisper) → LLM (open weights) → TTS (e.g. Piper / Kokoro / XTTS) → speaker
```

With that path, *you* own turn-taking, barge-in, and VAD — everything Gemini currently gives you for free. That is a **different adapter shape** than `open_session() → send/receive`.

The good news: the port is abstract enough that a `ComposedLiveAdapter` can hide an STT→LLM→TTS pipeline behind the same `LiveSessionPort` and emit the same normalized events. That is the elegant target — but building robust turn-taking and barge-in without native VAD is genuinely hard, and this is the real project, not a weekend.

---

## What it would take — in order

1. **Recover and de-risk what exists** *(days).* Bring the `dev` multi-provider code to `main`, add `LLM_PRIMARY_PROVIDER` / `LLM_FALLBACK_PROVIDER` to [`config.py`](../apps/backend/src/truefit_infra/config.py), wire the WS layer to `create_live_adapter()`, and delete the orphaned `.pyc` files. Outcome: Gemini↔OpenAI swappability plus fallback, immediately.
2. **Extract `VoiceAgentRuntime`** *(~1 week).* Domain-neutral, port-typed, tools-as-input. The interview becomes consumer #1. Resolves Gap 1; tighten Gap 2 in the same pass.
3. **Prove reusability with a second use case** *(days).* A meeting note-taker that reuses the runtime with different tools and prompt. This is what makes it *infrastructure* — and it satisfies the 3-month milestone's "first non-interview use case."
4. **Build `ComposedLiveAdapter` for the free/open path** *(weeks — the actual bet).* VAD + STT + open LLM + TTS behind `LiveSessionPort`. This is what makes "free models first-class" true rather than aspirational.
5. **Decide the product surface** *(unresolved; changes everything above).* SDK vs hosted API vs self-host. Determines auth, multi-tenancy, and whether the DB/domain layer ships at all.
6. **Build an eval pipeline** *(should start alongside step 2, not after).* Model-agnostic only means something if we can measure it. Without evals, swapping Gemini for OpenAI or an open-model composed pipeline is a guess, and regressions from prompt, tool or adapter changes go unnoticed. Scope to design:
   - **Per-provider comparison:** run the same scripted scenarios through each `LiveSessionPort` adapter and compare results.
   - **Voice metrics:** time to first audio, turn latency, barge-in / interruption handling, and STT word error rate on fixed audio fixtures.
   - **Agent behaviour:** tool-call correctness (right tool, right args, right order), for example that the interviewer never advances before `persist_answer`.
   - **Use-case scorecards:** one per consumer (interview, meeting copilot), with LLM-as-judge or rubric scoring for conversation quality.
   - **Regression gating:** a fixed scenario set that runs in CI on adapter, prompt and runtime changes, plus a cost-per-session figure so the free/open path can be compared against paid providers.
   - **Open questions:** scripted or simulated caller (TTS-driven audio in, text-only shortcut for cheap runs), where fixtures live, and what pass thresholds are.

---

## The strategic read

Steps 1–3 are mostly **refactoring of work already done**, and they yield a shippable model-agnostic voice infra for *paid* providers. Step 4 is the differentiator and the real risk.

If credits (Voice Bridge and similar) come through, the 3-month milestone can ship on steps 1–3 alone, with step 4 as the thing built toward — which de-risks the entire pivot. The recommended first move is step 1 → step 2, because it unblocks everything else and turns "the interview app" into "the first app on the platform."

---

## Decisions made

- **Product surface:** SDK first, offered over HTTP for web and mobile apps. Hosted API later.
- **Name:** Soro. The interview app keeps the TrueFit name and lives on the `truefit` branch as a reference consumer.
- **Layout:** `packages/` inside this repo.
- **First use cases:** interviews (exists), a personal OS assistant that talks to the user's knowledge repo and calendar, and a meeting copilot.
- **Free stack direction:** Deepgram for streaming STT and TTS, with OpenRouter's free models as a fallback.

## Open decisions

- **Free path at GA:** first-class supported target, or a best-effort tier?
- **Credit programs:** which are open (Voice Bridge and others)?
- **Connector standard:** how far to lean on MCP versus OpenAPI versus plain functions.
- **Hosted API:** auth model, tenancy, and how per-user credentials (for example Google tokens) are held.
- **Whether to keep the `truefit` branch** or move the interview app under `examples/` on `main`, since a diverging branch needs regular merges to avoid rotting.
