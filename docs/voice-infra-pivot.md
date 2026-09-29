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

## What's actually in the repo today

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
| Step 1: recover multi-provider code, factory in WS layer | Done (merged from `dev`; fallback default fixed to `none`, blank env values handled) |
| Gap 1: `VoiceAgentRuntime` extraction | Done: `truefit_core/agents/runtime/` (see below) |
| Step 2 remainder: tighten the port (Gap 2) | Done (see below) |
| Step 3: second use case (meeting copilot) | Not started |
| Step 4: `ComposedLiveAdapter` (Gap 3) | Not started |
| Step 6: eval pipeline | Not started |

Also fixed while getting a clean baseline: `Candidate.attach_resume()` (callers never passed the asset id), `JobService.create_job()` / `CreateJobCommand` (out of sync with the `Job` aggregate, now take `created_by` and `requirements`), and a test helper that turned `skills=[]` into default skills. Unit suite: 241 passing.

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

## Open decisions

- **Product surface:** SDK, hosted API, or self-host? (Blocks auth/multi-tenancy design.)
- **First non-interview use case:** meeting notes vs note-taking vs something else?
- **Free/open model shortlist:** which STT / LLM / TTS components for the composed path?
- **Credit programs:** which are currently open (Voice Bridge, others)?
- **How far "to some extent" goes:** is the free path a first-class supported target at GA, or a best-effort tier?
