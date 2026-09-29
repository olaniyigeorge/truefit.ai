# Pivot Review: Interview Product → Model-Agnostic Voice Infrastructure

**Status:** Assessment — informs the pivot decided 2026-09-28
**Date:** 2026-09-29
**Scope:** What it would actually take to turn TrueFit.ai from an AI-interview product into reusable, model-agnostic infrastructure for voice agents (interviews, meetings, note-taking, and other applications built on top).

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

## The gaps

### Gap 1 — Coupling leaks above the port (blocks "others can build on it")

The port is clean; the layers above it are not yet reusable.

- [`LiveInterviewAgent`](../apps/backend/src/truefit_core/agents/interviewer/live_interview_agent.py#L18) imports the **concrete** `GeminiLiveAdapter` and type-hints against it (lines 18, 93) rather than `LiveSessionPort`. It also hard-imports `INTERVIEW_TOOLS`, `build_system_prompt`, `InterviewContext`, and `InterviewOrchestrationService`. The "agent" *is* the interview product — it is not a reusable voice-agent runtime.
- The WebSocket layer [hardcodes `GeminiLiveAdapter()`](../apps/backend/src/truefit_api/api/v1/ws/interview_websocket.py#L96) in `get_gemini_live()`; it should resolve through the factory.
- The [tools](../apps/backend/src/truefit_core/agents/interviewer/tools.py) (`record_question`, `persist_answer`, `complete_interview`, `flag_interrupt`) are interview-domain concepts hard-wired into the agent's dispatcher.

**What it takes:** extract a domain-neutral `VoiceAgentRuntime` — the two-loop send/receive engine plus tool dispatch — that depends only on `LiveSessionPort` and takes tools, system prompt, and tool-handlers as *inputs*. The interview becomes the first *consumer* of the runtime, not the runtime itself. This is a refactor, not a rewrite: the callback seam (`on_audio_output`, `on_text_output`, `on_interrupt`, `on_turn_complete`) already exists.

### Gap 2 — Gemini's shape leaks into the port

`LiveSessionPort` assumes the provider owns the whole realtime loop, and even documents that output sample rate is not normalized ("*Gemini Live returns 24kHz*"). `send_image` and the `go_away` event are Gemini-isms. Fine for two similar realtime APIs; leaky for true model-agnosticism. Minor — worth tightening while generalizing for Gap 1.

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
