# Architecture

TrueFit.AI is a monorepo with three parts:

| Path | What it is |
|------|------------|
| `packages/soro` | Soro, a provider-neutral realtime voice SDK (Python). Depends on no app. See [packages/soro/README.md](../packages/soro/README.md). |
| `apps/backend` | FastAPI interview app. A reference consumer of Soro. |
| `apps/frontend` | React/Vite client (interview room, recruiter dashboards). |

The product is an AI interviewer: a candidate joins a browser room, talks to a
live voice model, and the backend records questions and answers. The
infrastructure underneath is being generalised into Soro, see
[voice-infra-pivot.md](voice-infra-pivot.md) for the direction and status.
REST endpoints, WebSocket events and auth are documented in [api.md](api.md).

## Repository layout

```
packages/soro/src/soro/
  ports.py            LiveSessionPort, AdapterCapabilities, LIVE_EVENT_TYPES
  tools.py            ToolSpec, normalize_tools
  errors.py           SoroError, CapabilityNotSupported
  runtime/            VoiceAgentRuntime, ToolRegistry, SessionComplete
  adapters/           gemini, openai, fallback, factory (create_live_adapter)
  audio/              PcmResampler, turn detection (EnergyTurnDetector)
  transport/webrtc.py AudioBridge, AgentAudioTrack (extra: soro[webrtc])
  testing.py          FakeLiveAdapter for consumer tests
apps/backend/
  src/truefit_core/   domain, application (ports, services), agents
  src/truefit_infra/  db, auth, cache, queue, llm factory, realtime (WebRTC)
  src/truefit_api/    FastAPI app, HTTP routers, WebSocket endpoint
  src/truefit_workers/ placeholders, see "Known gaps"
  alembic/            migrations
apps/frontend/src/    components, pages, hooks, providers
scripts/              dev.sh, deploy.sh, setup-gcp.sh
```

## Backend layers (hexagonal)

Dependencies point inward: `truefit_api` and `truefit_infra` depend on
`truefit_core`, never the reverse. A test fails if anything under
`truefit_core` imports infra, api or workers.

| Layer | Contains |
|-------|----------|
| `truefit_core/domain` | Aggregates: `Interview` (questions, answers, turns, status rules), `Job`, `Candidate`, `Application`, `User`, `Org`, `Evaluation`. No framework imports. |
| `truefit_core/application` | Ports in `ports.py` (repositories, `LLMPort`, `QueuePort`, `CachePort`, `StoragePort`), commands and queries, and services (`InterviewOrchestrationService`, `JobService`, `CandidateService`, `EvaluationService`, `UserService`, `InterviewSweeper`). |
| `truefit_core/agents` | `interviewer/` (prompt, tools, handlers, context, `LiveInterviewAgent`) and `evaluator/`. |
| `truefit_infra` | Adapters: SQLAlchemy repositories (`db/`), Firebase and JWT auth (`auth/`), Redis cache and queue, `llm/factory.py` (maps app config onto Soro), and `realtime/` (WebRTC glue). |
| `truefit_api` | `main.py` (app, lifespan, CORS, routers), HTTP routers under `api/v1/http`, and the interview WebSocket under `api/v1/ws`. All routes are under `/api/v1`. |

Session-start wiring lives in `interview_websocket.py`: `get_live_adapter()`,
`get_orchestration()` and the repository providers are FastAPI dependencies.

### Interview lifecycle

Domain status (`InterviewStatus`): `scheduled` -> `active` -> `completed` ->
`evaluated`, with `abandoned` reachable from `scheduled` or `active`.
Persistence maps an `Interview` onto the `interview_sessions` and
`interview_turns` tables (`SessionStatus` is a separate, coarser enum there).

`InterviewSweeper` runs as a background task started in the app lifespan. Every
60 seconds it abandons active interviews older than 45 minutes
(`reason="sweeper:timeout_exceeded"`).

## Where Soro ends and the app begins

Soro owns everything that is not interview-specific:

| Concern | Soro | Interview app |
|---------|------|---------------|
| Model access | `LiveSessionPort`, Gemini and OpenAI adapters, `FallbackLiveAdapter`, `create_live_adapter` | `truefit_infra/llm/factory.py` reads `AppConfig` and calls Soro |
| Session loops, tool dispatch, resume handling | `VoiceAgentRuntime`, `ToolRegistry` | `LiveInterviewAgent` supplies prompt, tools, handlers, opening message |
| Audio transport | `AudioBridge`, `AgentAudioTrack`, `PcmResampler` | `WebRTCClient`, `WebRTCSignaling`, `DataChannelManager` |
| Turn detection | `EnergyTurnDetector` (`soro.audio.turn`) | Receives activity callbacks, decides mic gating |
| Domain state | none | Orchestration service, repositories, Redis, events |

The backend installs Soro from `../../packages/soro` via `requirements.txt`, so
`pip install -r requirements.txt` must run from `apps/backend` (the `Makefile`,
`scripts/dev.sh` and `scripts/deploy.sh` all do).

### The port

`LiveSessionPort` (`soro/ports.py`) is the only thing agents and the runtime
see. An adapter is used as `async with adapter.open_session(prompt, tools) as s`.

| Part | Detail |
|------|--------|
| Send | `send_audio`, `send_client_content` (text turn), `send_tool_response`; optional `send_image`, `send_activity_start`, `send_activity_end`, `send_audio_stream_end` |
| Receive | `receive()` yields `(event_type, data)` for the whole session, across turns |
| Events | `audio`, `text`, `input_text`, `tool_call`, `turn_complete`, `interrupted`, `session_ending`, `session_resumed` |
| Capabilities | `AdapterCapabilities`: `input_sample_rate` (16 kHz default), `output_sample_rate` (24 kHz default), `supports_images`, `native_vad` |
| Tools | Provider-neutral `ToolSpec`; each adapter translates it |

`send_image` raises `CapabilityNotSupported` when unsupported, so frames are
never dropped silently. The Gemini adapter declares `native_vad=False` (it runs
with automatic activity detection off and expects the caller to signal turn
boundaries). `FallbackLiveAdapter` refuses at construction if its two adapters
disagree on sample rates or `native_vad`.

Provider selection comes from app config: `LLM_PRIMARY_PROVIDER` (`gemini` or
`openai`, blank means gemini) and `LLM_FALLBACK_PROVIDER` (`gemini`, `openai` or
`none`). Model overrides: `GEMINI_LIVE_MODEL`, `OPENAI_REALTIME_MODEL`. The
fallback engages if the primary fails to open or fails before producing any
output; failures after output has started propagate.

Gemini sessions resume on transient close codes (1001, 1006, 1011, 1012, 1013),
up to three consecutive reconnects. With a resume handle the conversation
continues server-side, otherwise the adapter restarts and replays the opening
message. It then emits `session_resumed`.

### The runtime and the interview agent

`VoiceAgentRuntime` runs two loops per session and cancels one when the other
ends:

- send loop: mic audio stream -> `session.send_audio`
- receive loop: session events -> callbacks and tool handlers

It depends only on `LiveSessionPort`. Inputs: system prompt, `ToolRegistry`,
audio input stream, `RuntimeCallbacks` (audio, text, input text, interrupt,
turn complete), plus optional `opening_message`, `resume_message` and
`on_error`. A tool handler ends the session by raising `SessionComplete` or by
calling `runtime.stop()`. Other handler exceptions go back to the model as an
error result. On `session_resumed` the runtime fires `on_interrupt` (to drop
stale audio) and sends `resume_message` unless the adapter restarted.

`LiveInterviewAgent` (`truefit_core/agents/interviewer`) builds a runtime per
interview. It supplies:

| Input | Source |
|-------|--------|
| System prompt | `build_system_prompt(context)` |
| Tools | `INTERVIEW_TOOLS` plus `InterviewToolHandlers` |
| Opening message | job title, required skills, topics and question cap as JSON, then a greeting instruction |
| Resume message | apologise briefly and ask the candidate to repeat their last answer |
| `on_error` | `abandon_interview(reason="agent_error")` |

Interview tools:

| Tool | Effect |
|------|--------|
| `record_question` | Registers the question about to be asked via `ask_next_question`. Rejected if one is already active. |
| `persist_answer` | Saves the answer via `submit_answer`. Stops the session when the question cap is reached. |
| `complete_interview` | Publishes `interview.agent_ending` to the queue and ends the session (no tool response). |
| `flag_interrupt` | Writes `interrupt:{interview_id}` to Redis and publishes `interview.interrupted`. |

## Connection flow

One WebSocket per interview: `/api/v1/ws/interview/{job_id}/{candidate_id}`.
It is a control channel only. Audio never travels over it. Message shapes are
in [api.md](api.md). `InterviewConnection.run()` does, in order:

1. Create the interview (`start_interview`) and build the `InterviewContext`.
2. Send `session_started` with `interview_id` and a fresh `session_id`.
3. Check the adapter's `input_sample_rate` matches the bridge (16 kHz), then
   create `WebRTCSignaling` sized from the adapter's `output_sample_rate`.
4. Start the WS receive loop and the interrupt monitor as tasks.
5. Wait up to 30 seconds for the browser's `webrtc_offer` to be handled. On
   timeout, send an error and stop.
6. Close the mic, register the bridge's activity callbacks, wire the data
   channel handler.
7. Start `LiveInterviewAgent`. If the agent returns without an end reason, the
   connection reports an error rather than leaving a live mic with no agent.
8. `gather` the agent, receive loop and interrupt monitor until completion,
   `end_session`, disconnect or error. The signaling object is always closed in
   `finally`.

### Signaling

```
Browser                        Backend (FastAPI)
   |--- WS connect ------------->|  start_interview
   |<-- session_started ---------|
   |--- webrtc_offer (SDP) ----->|  WebRTCSignaling.handle_offer
   |                             |   RTCPeerConnection + WebRTCClient
   |                             |   add outbound audio track, then answer
   |<-- webrtc_answer (SDP) -----|
   |<-> ice_candidate (trickle) <|
   |==== WebRTC: mic audio, agent audio, data channel, video ====|
   |--- end_session / ping ----->|  pong, session_ended
```

The outbound audio track is added before `createAnswer` so it is negotiated.
Trickle candidates that arrive before the offer are dropped. Clients register
in `WebRTCClientRegistry` by session id.

ICE servers: both the browser (via `GET /api/v1/turn/credentials`, authenticated)
and the backend peer connection in `realtime/signaling.py` use
`realtime/ice.py`, which returns Google STUN plus a TURN relay when
`TURN_SERVER_URL`, `TURN_USERNAME` and `TURN_CREDENTIAL` are set. No TURN
credentials are kept in source. The frontend hook `useInterviewSession.ts` still
declares its own STUN server for its peer connection.

Access control: all routers except health and the sign-in exchange require a
JWT, each endpoint then checks role and ownership
(`truefit_infra/auth/authorization.py`), and the interview WebSocket takes the
JWT in a `token` query parameter and only admits the interviewed candidate or an
admin (`api/v1/ws/auth.py`). See [api.md](./api.md#access-rules).

### The three channels

| Channel | Carries |
|---------|---------|
| WebSocket | Signaling, `session_started`/`session_ended`, `transcript`, `interrupt`, `error`, `ping`/`pong` |
| WebRTC media | Mic audio in, agent audio out, optional camera and screen video |
| WebRTC data channel | JSON events. Inbound: `screen_share_start`, `screen_share_stop`, `clarification_request`, `ping` (answered with `pong`). Currently logged only. Outbound events are queued (200 max) and sent once the channel opens. |

`WebRTCClient` (`truefit_infra/realtime/webrtc_client.py`) routes tracks on
arrival: audio to the `AudioBridge`, video to the `FrameSampler`, data channel
to `DataChannelManager`.

## Audio path

```
Browser mic (Opus, 48 kHz)
   -> aiortc track
   -> AudioBridge._pump_inbound: resample to 16 kHz mono s16, 20 ms chunks
        -> turn detector (EnergyTurnDetector) -> ActivityStart / ActivityEnd
        -> mic gate (closed while the agent speaks) -> inbound_queue (100)
   -> audio_input_stream() -> VoiceAgentRuntime send loop -> adapter.send_audio
                                   model
   <- adapter "audio" events (24 kHz mono s16) <- VoiceAgentRuntime receive loop
   -> InterviewConnection._on_audio_output -> AudioBridge.push_audio
   -> outbound_queue (500) -> AgentAudioTrack.recv: one chunk per call,
      resampled to 48 kHz, paced at 20 ms
Browser speaker
```

Rates are 16 kHz in and 24 kHz out by default, but the output rate is read
from the adapter's capabilities. The OpenAI adapter upsamples the bridge's
16 kHz to the 24 kHz its GA API requires.

### Turn handling

The Gemini adapter has no native VAD here, so the bridge decides when the
candidate starts and stops speaking and the app tells the adapter.

- `EnergyTurnDetector` (`soro/audio/turn.py`) is pure Python. It learns a noise
  floor (first 300 ms, then adaptive) so steady noise such as a fan raises the
  floor instead of holding a turn open. Two thresholds (3.0x and 1.8x the floor,
  with absolute minimums) give hysteresis. A turn starts after 100 ms of
  sustained speech and ends after 800 ms of silence. Time is counted in audio,
  not wall clock. The `TurnDetector` protocol allows other detectors;
  `create_turn_detector("energy")` is the only one that ships.
- `AudioBridge._handle_turn_event` turns detector events into callbacks. After
  a turn ends the bridge locks (ignores new speech) until
  `on_agent_responded()`, and ignores a start within 0.5 s of the last one.
  Timeouts unlock the lock if the agent never responds.
- On candidate start, the connection calls `adapter.send_activity_start()`. On
  end it closes the mic, drains stale inbound chunks, then calls
  `send_activity_end()`, which is the turn boundary that makes the model reply.
- Echo control: the mic starts closed, is closed again while the agent speaks,
  and the bridge suppresses inbound audio for a cooldown (600 ms) after the
  agent stops.

On the agent's `turn_complete` (`_on_turn_complete`): close the mic, wait up to
0.8 s for outbound audio to drain, wait 200 ms for the last frames to play, clear
the outbound queue and resampler state, open the mic, and unlock the detector.

### Interrupts

`flag_interrupt` writes a directive to Redis. The connection polls that key
every 50 ms and forwards an `interrupt` message to the browser, then deletes
the key. Directives: `clarification` maps to `acknowledge_and_continue`,
`noise` to `resume`, anything else to `stop_and_listen` (audio is suppressed for
500 ms). Separately, the model's own `interrupted` event calls `on_interrupt`,
which clears the outbound queue so the candidate stops hearing stale speech.

## Persistence

The backend uses SQLAlchemy 2 (async). Models are in
`truefit_infra/db/models.py`. PostgreSQL is the target (UUID keys, JSONB);
`main.py` also configures an SQLite engine when `DATABASE_URL` contains
`sqlite`. The app calls `create_all` on startup. Alembic is configured
(`apps/backend/alembic`) but the three revision files in `alembic/versions` do
not form a single chain (two have no parent), so treat them as historical and
check before relying on `alembic upgrade`.

### Entities

| Table | Purpose | Key links |
|-------|---------|-----------|
| `orgs` | Companies | `created_by` -> users |
| `users` | Identity. Roles: `admin`, `recruiter`, `candidate` | `org_id` -> orgs (nullable) |
| `candidate_profiles` | Candidate details, skills | `user_id` -> users, `resume_asset_id` -> media_assets |
| `job_listings` | Jobs and interview config. Status: `draft`, `open`, `closed` | `org_id`, `created_by` |
| `rubrics`, `rubric_criteria` | Org-owned scoring definitions | `org_id`, `rubric_id` |
| `applications` | Job to candidate link. Status: `new`, `interviewing`, `shortlisted`, `rejected`, `hired` | `job_id`, candidate profile |
| `interview_sessions` | One row per interview round. Has `round`, `status`, `started_at`, `ended_at`, `agent_version`, `context_snapshot`, `realtime` (JSON) | `application_id` |
| `interview_participants` | Who was in a session (candidate, recruiter, agent, system) | `session_id`, `user_id` |
| `interview_turns` | Ordered utterances: `seq`, `speaker`, `modality`, `turn_text`, `payload` | `session_id` |
| `media_assets` | Audio, video, recordings, images, resumes, reports. Storage `local` or `gcs` | optional session and turn |
| `transcripts` | Text derived from audio | session, turn, asset |
| `evaluations` | Result and `recommendation` (`strong_yes` to `strong_no`), optional report asset | `session_id`, rubric |
| `evaluation_scores` | Per-criterion scores | `evaluation_id`, criterion |
| `session_events` | Audit log (ws/rtc connect and disconnect, interrupts, barge-in, tool calls, mute) | `session_id` |

```
orgs -> job_listings -> applications <- candidate_profiles <- users
                            |
                     interview_sessions -> interview_turns -> transcripts
                        |        |  \-> interview_participants, session_events
                        |        \-> evaluations -> evaluation_scores
                        \-> media_assets
```

Redis is used for the cache (interrupt signals, via `CachePort`) and for domain
events (`QueuePort.publish` appends to `events:{event_type}` streams).

## Frontend

React with Vite and TypeScript, using pnpm. The interview room is
`components/InterviewRoom.tsx`, and the session logic (WebSocket plus peer
connection, `webrtc_offer` handling) is in `hooks/useInterviewSession.ts`.

## Deployment

Target: a single GCP Compute Engine VM, no containers.

1. Pushing to `main` triggers `.github/workflows/deploy.yml` (environment
   `prod`). It copies `scripts/deploy.sh` to the VM over SSH and runs it.
   Secrets used: `GCP_SSH_PRIVATE_KEY`, `GCP_VM_IP`, `GCP_VM_USER`.
2. `deploy.sh` installs system packages (nginx, redis-server, Node 20, Python),
   pulls `main`, creates a venv in `apps/backend`, and runs
   `pip install -r requirements.txt` (which installs Soro from the monorepo).
3. It writes a systemd unit `truefit-api` running
   `uvicorn src.truefit_api.main:app --port 8000 --workers 2` with
   `apps/backend/.env` as its environment file.
4. It builds the frontend (`npm install`, `npm run build`).
5. It writes an nginx site: static frontend at `/`, `/api/` proxied to the
   backend, and `/ws/` proxied to `/api/v1/ws/` with WebSocket upgrade headers
   and a one-hour read timeout.
6. Health checks hit Redis, the backend port and nginx.

`scripts/setup-gcp.sh` provisions the VM. Local development uses `make dev`
(`scripts/dev.sh`) or `make dev-backend` and `make dev-frontend`. Soro has its
own targets: `make soro-test` and `make soro-smoke`.

Required backend settings are in `apps/backend/env.example` and
`truefit_infra/config.py` (database, Redis, Gemini key and model, TURN, auth,
plus the optional `OPENAI_*` and `LLM_*` provider settings above).

## Known gaps

- `truefit_workers` holds two empty placeholders (`evaluation_worker.py`,
  `report_worker.py`). Nothing publishes `interview.completed` yet; the only
  events emitted are `interview.agent_ending` and `interview.interrupted`.
- `FrameSampler` samples camera (every 5 s) and screen (every 2 s) frames to a
  queue, but nothing forwards them to the adapter, and the OpenAI adapter does
  not support images.
- Data channel events are logged, not yet fed to the agent.
- Not started (see [voice-infra-pivot.md](voice-infra-pivot.md)): connector
  layer, composed STT/LLM/TTS adapter, hosted API, eval harness, neural turn
  detector.
