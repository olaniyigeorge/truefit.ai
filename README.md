# truefit.ai
Truefit.ai is a Gemini-powered live AI agent that automates hiring by conducting real-time interviews, evaluating candidates, and generating recommendations. Companies create job listings, and candidates start instant AI interview sessions with adaptive questioning and structured reports.












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