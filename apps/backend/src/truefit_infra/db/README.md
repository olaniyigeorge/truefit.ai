# truefit.ai
Truefit.ai is a Gemini-powered live AI agent that automates hiring by conducting real-time interviews, evaluating candidates, and generating recommendations. Companies create job listings, and candidates start instant AI interview sessions with adaptive questioning and structured reports.








truefit.ai/
├─ apps/
│  ├─ frontend/                      # Vite + React (already)
│  │  ├─ src/
│  │  ├─ public/
│  │  ├─ package.json
│  │  └─ vite.config.ts
│  |
|  |--backend/
    ├── src/
    │   │
    │   ├── truefit_api/                        # Transport layer only — HTTP + WebSocket
    │   │   ├── __init__.py
    │   │   ├── main.py                         # FastAPI app factory, lifespan
    │   │   ├── dependencies.py                 # FastAPI Depends() factories for all services
    │   │   └── api/
    │   │       └── v1/
    │   │           ├── __init__.py
    │   │           ├── router.py               # Mounts all sub-routers
    │   │           ├── http/                   # ← ADD THIS (you have ws/ but no http/)
    │   │           │   ├── __init__.py
    │   │           │   ├── jobs.py             # POST /jobs, GET /jobs/{id}, PATCH, DELETE
    │   │           │   ├── candidates.py       # POST /candidates, GET, PATCH, resume upload
    │   │           │   ├── interviews.py       # GET /interviews/{id}, list, transcript
    │   │           │   └── evaluations.py      # GET /evaluations/{id}, report download URL
    │   │           └── ws/
    │   │               ├── __init__.py
    │   │               └── interview.py        # ws/interview/{job_id}/{candidate_id}
    │   │
    │   │
    │   ├── truefit_core/                       # Zero infra imports — pure Python business logic
    │   │   ├── __init__.py
    │   │   ├── common/
    │   │   │   ├── __init__.py
    │   │   │   ├── utils.py                    # logger, shared helpers
    │   │   │   └── exceptions.py              # ← ADD: DomainError, NotFoundError,
    │   │   │                                  #   ConflictError, PermissionDeniedError
    │   │   │                                  #   (typed exceptions > bare ValueError)
    │   │   │
    │   │   ├── domain/
    │   │   │   ├── __init__.py
    │   │   │   ├── job.py
    │   │   │   ├── candidate.py
    │   │   │   ├── interview.py
    │   │   │   └── evaluation.py
    │   │   │
    │   │   ├── application/
    │   │   │   ├── __init__.py
    │   │   │   ├── ports.py
    │   │   │   ├── commands/
    │   │   │   │   ├── __init__.py
    │   │   │   │   ├── interview.py
    │   │   │   │   ├── job.py
    │   │   │   │   └── candidate.py
    │   │   │   ├── query/                      # already query/ (not queries/) — keep it
    │   │   │   │   ├── __init__.py
    │   │   │   │   ├── interview.py            # ← SPLIT by domain (currently one big file)
    │   │   │   │   ├── job.py
    │   │   │   │   ├── candidate.py
    │   │   │   │   └── evaluation.py
    │   │   │   └── services/
    │   │   │       ├── __init__.py
    │   │   │       ├── interview_orchestration.py
    │   │   │       ├── evaluation_service.py
    │   │   │       ├── job_service.py
    │   │   │       └── candidate_service.py
    │   │   │
    │   │   └── agents/                         # ← MOVE agents/ INTO core (not alongside it)
    │   │       └── interviewer/                # Agent is core business logic, not infra
    │   │           ├── __init__.py
    │   │           ├── prompts.py              # build_system_prompt(), all prompt builders
    │   │           ├── tools.py                # INTERVIEW_TOOLS declaration + _classify_interrupt
    │   │           └── context.py             # InterviewContext dataclass
    │   │
    │   │
    │   ├── truefit_infra/                      # Concrete adapters — implements every port
    │   │   ├── __init__.py
    │   │   ├── config.py                       # pydantic-settings — all env vars in one place
    │   │   ├── container.py                    # ← ADD: wires all adapters, exposes singletons
    │   │   │
    │   │   ├── agent/                          # ← KEEP but rename responsibility:
    │   │   │   ├── __init__.py                 # infra/agent owns the Gemini SDK connection only
    │   │   │   └── live_interview_agent.py     # LiveInterviewAgent — Gemini Live session manager
    │   │   │                                   # uses prompts/tools from truefit_core/agents/
    │   │   │
    │   │   ├── auth/
    │   │   │   ├── __init__.py
    │   │   │   ├── jwt.py                      # token encode/decode
    │   │   │   └── middleware.py               # FastAPI auth middleware / dependency
    │   │   │
    │   │   ├── db/
    │   │   │   ├── __init__.py
    │   │   │   ├── database.py                 # DatabaseManager ← already built
    │   │   │   ├── models/                     # ← ADD models/ package (currently flat)
    │   │   │   │   ├── __init__.py
    │   │   │   │   ├── base.py                 # DeclarativeBase, TimestampMixin
    │   │   │   │   ├── job.py                  # JobModel ORM
    │   │   │   │   ├── candidate.py            # CandidateModel ORM
    │   │   │   │   ├── interview.py            # InterviewSessionModel, InterviewTurnModel
    │   │   │   │   ├── evaluation.py           # EvaluationModel ORM
    │   │   │   │   └── media.py                # MediaAsset, InterviewParticipant, SessionEvent
    │   │   │   ├── repositories/               # ← ADD repositories/ package
    │   │   │   │   ├── __init__.py
    │   │   │   │   ├── job_repository.py       # SQLAlchemyJobRepository(JobRepository)
    │   │   │   │   ├── candidate_repository.py
    │   │   │   │   ├── interview_repository.py
    │   │   │   │   └── evaluation_repository.py
    │   │   │   └── alembic/                    # already exists — keep as-is
    │   │   │       ├── env.py
    │   │   │       ├── script.py.mako
    │   │   │       └── versions/
    │   │   │
    │   │   ├── cache/                          # ← RENAME from nothing (currently missing)
    │   │   │   ├── __init__.py
    │   │   │   └── redis_cache.py              # RedisCacheAdapter(CachePort)
    │   │   │
    │   │   ├── llm/
    │   │   │   ├── __init__.py
    │   │   │   ├── gemini_llm.py               # GeminiLLMAdapter(LLMPort) — standard gen
    │   │   │   └── gemini_live.py              # GeminiLiveAdapter — Live API session wrapper
    │   │   │
    │   │   ├── queue/
    │   │   │   ├── __init__.py
    │   │   │   └── redis_stream_queue.py       # RedisStreamQueueAdapter(QueuePort)
    │   │   │
    │   │   ├── realtime/                       # ← KEEP — WebRTC signalling lives here
    │   │   │   ├── __init__.py
    │   │   │   ├── signalling.py               # WebRTC offer/answer/ICE exchange
    │   │   │   └── audio_bridge.py             # PCM chunk routing between WebRTC and Gemini
    │   │   │
    │   │   └── storage/
    │   │       ├── __init__.py
    │   │       ├── local_storage.py            # LocalStorageAdapter(StoragePort) — dev/v1
    │   │       └── gcs_storage.py             # GCSStorageAdapter — production
    │   │
    │   │
    │   └── truefit_workers/                    # Background task workers
    │       ├── __init__.py
    │       ├── config.py                       # Worker-specific settings
    │       └── jobs/
    │           ├── __init__.py
    │           ├── evaluation_worker.py        # Consumes interview.completed → triggers evaluation
    │           └── report_worker.py            # Consumes evaluation.completed → generates PDF report
    │
    │
    ├── tests/
    │   ├── unit/
    │   │   ├── domain/                         # ← ADD: pure domain tests, zero IO
    │   │   │   ├── test_job.py
    │   │   │   ├── test_candidate.py
    │   │   │   ├── test_interview.py
    │   │   │   └── test_evaluation.py
    │   │   ├── application/                    # ← ADD: service tests with in-memory adapters
    │   │   │   ├── test_interview_orchestration.py
    │   │   │   └── test_evaluation_service.py
    │   │   └── agents/
    │   │       └── test_interrupt_classification.py
    │   ├── integration/                        # ← ADD (currently missing)
    │   │   ├── test_repositories.py            # real DB, test container or local PG
    │   │   └── test_redis_cache.py
    │   └── e2e/                               # ← ADD (future)
    │       └── test_interview_flow.py          # full WS session with mock Gemini
    │
    │
    ├── alembic.ini
    ├── pyproject.toml
    └── .env.example






truefit.ai/
├─ apps/
│  ├─ frontend/                      # Vite + React (already)
│  │  ├─ src/
│  │  ├─ public/
│  │  ├─ package.json
│  │  └─ vite.config.ts
│  │
│  └─ backend/
│     ├─ pyproject.toml              # Poetry/uv/pip-tools (pick one)
│     ├─ README.md
│     ├─ Dockerfile
│     ├─ .env.example
│     ├─ src/
│     │  ├─ truefit_api/             # FastAPI app package (thin)
│     │  │  ├─ __init__.py
│     │  │  ├─ main.py               # app factory + startup/shutdown
│     │  │  ├─ api/
│     │  │  │  ├─ __init__.py
│     │  │  │  ├─ v1/
│     │  │  │  │  ├─ __init__.py
│     │  │  │  │  ├─ routes/
│     │  │  │  │  │  ├─ health.py
│     │  │  │  │  │  ├─ auth.py
│     │  │  │  │  │  ├─ jobs.py
│     │  │  │  │  │  ├─ candidates.py
│     │  │  │  │  │  ├─ interviews.py
│     │  │  │  │  │  └─ realtime.py  # ws endpoints for live sessions
│     │  │  │  │  ├─ deps.py         # FastAPI dependencies
│     │  │  │  │  └─ schemas.py      # request/response DTOs (Pydantic)
│     │  │  ├─ middleware/
│     │  │  ├─ security/
│     │  │  ├─ settings.py           # env config (Pydantic Settings)
│     │  │  └─ telemetry/            # logging/tracing/metrics wiring
│     │  │
│     │  ├─ truefit_core/            # your real product logic (reusable)
│     │  │  ├─ __init__.py
│     │  │  ├─ domain/               # entities + value objects + rules
│     │  │  │  ├─ job.py
│     │  │  │  ├─ candidate.py
│     │  │  │  ├─ interview.py
│     │  │  │  └─ evaluation.py
│     │  │  ├─ application/          # use-cases (orchestrates domain)
│     │  │  │  ├─ commands/
│     │  │  │  ├─ queries/
│     │  │  │  ├─ services/          # business services
│     │  │  │  └─ ports.py           # interfaces: repo, queue, llm, storage
│     │  │  ├─ agents/               # Gemini live agent + prompting/tools
│     │  │  │  ├─ interviewer/
│     │  │  │  │  ├─ policy.py       # interview strategy
│     │  │  │  │  ├─ prompts.py
│     │  │  │  │  ├─ tools.py
│     │  │  │  │  └─ runner.py       # runs the live interview loop
│     │  │  │  ├─ scoring/
│     │  │  │  └─ safety/
│     │  │  ├─ workflows/            # multi-step flows
│     │  │  │  ├─ start_interview.py
│     │  │  │  ├─ process_turn.py
│     │  │  │  ├─ finalize_report.py
│     │  │  │  └─ export_results.py
│     │  │  └─ common/
│     │  │     ├─ errors.py
│     │  │     ├─ ids.py
│     │  │     ├─ clock.py
│     │  │     └─ utils.py
│     │  │
│     │  ├─ truefit_infra/           # adapters + infrastructure details
│     │  │  ├─ __init__.py
│     │  │  ├─ db/
│     │  │  │  ├─ models.py          # SQLAlchemy models (if using SQL)
│     │  │  │  ├─ session.py
|     |  |  |  |-- database.py       # contains a db manager that handles initialize the db, closing session, creating session with context manager, and getting sessions
│     │  │  │  └─ migrations/        # Alembic
│     │  │  ├─ repositories/         # implements ports.py repos
│     │  │  ├─ llm/
│     │  │  │  ├─ gemini_client.py
│     │  │  │  └─ streaming.py
│     │  │  ├─ realtime/
│     │  │  │  ├─ webrtc_tokens.py   # signing, token minting, etc
│     │  │  │  └─ session_store.py
│     │  │  ├─ queue/
│     │  │  │  ├─ pubsub.py          # GCP Pub/Sub adapter
│     │  │  │  └─ tasks.py           # Cloud Tasks adapter (optional)
│     │  │  ├─ storage/
│     │  │  │  └─ gcs.py             # store resumes, recordings, reports
│     │  │  └─ auth/
│     │  │     └─ firebase.py        # if using Firebase auth
│     │  │
│     │  └─ truefit_workers/         # background jobs (optional but common)
│     │     ├─ __init__.py
│     │     ├─ consumer.py           # Pub/Sub consumer entrypoint
│     │     └─ jobs/
│     │        ├─ transcribe.py
│     │        ├─ score_interview.py
│     │        └─ generate_report.py
│     │
│     ├─ tests/
│     │  ├─ unit/
│     │  ├─ integration/
│     │  └─ contract/
│     └─ scripts/
│        ├─ seed.py
│        └─ dev_run.sh
│
├─ packages/                         # shared code across apps (optional)
│  ├─ shared-types/                  # e.g. openapi types or zod schemas
│  └─ ui/                            # if you later share components
│
├─ infra/
│  ├─ gcp/
│  │  ├─ terraform/                  # Cloud Run, Pub/Sub, Cloud SQL, etc.
│  │  └─ cloudbuild/                 # CI/CD build configs
│  └─ local/
│     └─ docker-compose.yml          # local DB/redis/etc
│
├─ docs/
│  ├─ architecture.md
│  ├─ api.md
│  └─ runbook.md
│
├─ .github/
│  └─ workflows/                     # CI: lint/test/build/deploy
│
└─ README.md