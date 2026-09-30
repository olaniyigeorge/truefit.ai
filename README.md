# TrueFit.ai

Model-agnostic voice agent infrastructure, with AI interviews as the first application built on it.

TrueFit.ai runs real-time voice conversations between a person and an AI agent. The agent runtime talks to any realtime model through one small interface, so you can swap Gemini Live for OpenAI Realtime (or fail over between them) without touching the agent, the tools or the audio path.

**Stack:** FastAPI, WebRTC, Gemini Live API, OpenAI Realtime, React, PostgreSQL, Redis

## Status

This project is mid-pivot from a single AI interview product to reusable voice infrastructure. Here is where things stand, so you know what is real today.

| Area | State |
|------|-------|
| Interview product (jobs, candidates, live interviews, evaluations) | Working |
| Gemini Live and OpenAI Realtime adapters, env-driven selection, open-time fallback | Working |
| `soro`, the extracted SDK (port, runtime, adapters) | Working, the interview app imports it |
| Second use case: meeting copilot that guides you from your personal knowledge base | Planned |
| Composed pipeline for free and open models (streaming STT, open LLM, TTS) | Planned |
| Eval pipeline (per-provider comparison, latency, tool-call correctness) | Planned |
| SDK and hosted API | Planned |

The full assessment, gaps and plan live in [docs/voice-infra-pivot.md](./docs/voice-infra-pivot.md).

## How it fits together

The code follows a hexagonal layout. The core never imports infrastructure, and a test enforces that.

```
Browser mic/speaker
      |  WebRTC (Opus 48kHz)
      v
AudioBridge (resamples to the adapter's declared rates, 16kHz in and 24kHz out today)
      |
      v
VoiceAgentRuntime  <---- system prompt, tools, opening message, callbacks
      |  LiveSessionPort (normalised events)
      v
GeminiLiveAdapter | OpenAIRealtimeAdapter | FallbackLiveAdapter
```

- **`LiveSessionPort`** (`packages/soro/src/soro/ports.py`) is the seam between agents and providers. Providers emit normalised `(event_type, data)` events: `audio`, `text`, `input_text`, `tool_call`, `turn_complete`, `interrupted`, `session_ending`. Each adapter also declares `capabilities` (sample rates, image support, whether it has native turn detection) and takes provider-neutral `ToolSpec` tools.
- **`VoiceAgentRuntime`** (`soro.runtime`) owns the send loop, the receive loop, tool dispatch and lifecycle. It depends only on the port.
- **`ToolRegistry`** keeps each tool's declaration and handler together, so a mismatch fails at startup instead of mid-call.
- **`create_live_adapter`** (`soro.adapters.factory`) picks the provider from arguments you pass in and wraps it in a fallback if one is set. The app's `truefit_infra/llm/factory.py` just feeds it the app config.

A new use case supplies four things and reuses everything else:

```python
runtime = VoiceAgentRuntime(
    adapter=create_live_adapter(),
    system_prompt="You are a note taker...",
    tools=ToolRegistry().register(NOTE_DECLARATION, save_note),
    audio_input_stream=mic_chunks,          # 16kHz mono s16 PCM
    callbacks=RuntimeCallbacks(on_audio_output=play),
    opening_message="Say hello and ask what we are working on.",
)
await runtime.run()
```

`LiveInterviewAgent` is the reference consumer: it supplies the interview prompt, tools and handlers and delegates the rest to the runtime.

## Choosing a model provider

Set these in `apps/backend/.env`:

```
LLM_PRIMARY_PROVIDER=gemini      # gemini | openai
LLM_FALLBACK_PROVIDER=none       # gemini | openai | none
GEMINI_API_KEY=...
GEMINI_LIVE_MODEL=...            # optional, overrides the Gemini Live model
OPENAI_API_KEY=...               # only needed if OpenAI is primary or fallback
OPENAI_REALTIME_MODEL=...        # optional, defaults to gpt-realtime-mini-2025-12-15
```

Fallback happens when the primary fails to open a session (network, auth, timeout) or fails before it has produced any output, in which case the opening message is replayed on the fallback. A session that dies after the conversation has started is not recovered by the wrapper, but the Gemini adapter reconnects and resumes its own session on transient errors.

## Project structure

```
truefit.ai/
  packages/
    soro/                     The SDK: port, runtime, adapters, tools. Depends on no app.
      src/soro/  ports, tools, runtime/, adapters/, audio/, testing
      tests/                  Unit and contract tests (no interview code)
  apps/                       The interview app, a reference consumer of Soro
    frontend/                 Vite, React, TypeScript
      src/  components, pages, hooks, helpers, context, providers, lib
    backend/
      src/
        truefit_api/          HTTP and WebSocket transport
          api/v1/http/        auth, users, orgs, jobs, candidates,
                              applications, interviews, turn, health
          api/v1/ws/          interview_websocket.py
        truefit_core/         Domain and application logic (no infra imports)
          domain/             job, candidate, interview, evaluation, ...
          application/        ports, commands, query, services
          agents/
            interviewer/      Interview prompt, tools, handlers, agent
            evaluator/
        truefit_infra/        Adapters
          llm/                factory (feeds app config to Soro), gemini_llm
          realtime/           WebRTC client, audio bridge, signaling
          db/  auth/  cache/  queue/  config.py
        truefit_workers/      Evaluation and report workers
      tests/                  unit, integration, e2e
      alembic/                Database migrations
  docs/                       Architecture, API, auth, WebRTC, pivot review
  scripts/                    dev.sh, deploy.sh, setup-gcp.sh
  Makefile  CONTRIBUTING.md  SECURITY.md  LICENSE
```

## Quick start

**Prerequisites:** Python 3.12, Node.js 18+, pnpm, PostgreSQL, Redis

```bash
git clone https://github.com/olaniyigeorge/truefit.ai.git
cd truefit.ai

make setup        # creates the backend venv, installs deps, copies env files
# edit apps/backend/.env with your keys and database URL

cd apps/backend && .venv/bin/alembic upgrade head && cd ../..
make dev          # starts backend (port 8000) and frontend together
```

Or run each side on its own with `make dev-backend` and `make dev-frontend`. Interactive API docs are at `http://localhost:8000/api/docs` while the backend runs.

## Testing

```bash
cd apps/backend
.venv/bin/python -m pytest tests/unit
```

The unit suite uses fake providers, so it needs no API keys, database or Redis. It covers the runtime, the fallback adapter, the factory, the interview agent and tools, the domain, and the layer boundary between core and infrastructure.

## Documentation

| Doc | Description |
|-----|-------------|
| [docs/voice-infra-pivot.md](./docs/voice-infra-pivot.md) | Pivot assessment, gaps, progress and plan |
| [docs/architecture.md](./docs/architecture.md) | System design, components, data flow |
| [docs/api.md](./docs/api.md) | REST endpoints, WebSocket events, data models |
| [docs/auth.md](./docs/auth.md) | Firebase OAuth and JWT |
| [docs/webrtc.md](./docs/webrtc.md) | WebRTC and WebSocket real-time architecture |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Local setup, conventions, how to contribute |
| [SECURITY.md](./SECURITY.md) | Vulnerability reporting, secrets management |

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md) to get started.

## License

[MIT](./LICENSE)
