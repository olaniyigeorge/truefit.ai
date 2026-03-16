# truefit.ai
Truefit.ai is a Gemini-powered live AI agent that automates hiring by conducting real-time interviews, evaluating candidates, and generating recommendations. Companies create job listings, and candidates start instant AI interview sessions with adaptive questioning and structured reports.


## Project Structure

```
truefit.ai/
├─ apps/
│  ├─ frontend/                      # Vite + React
│  │  ├─ src/
│  │  ├─ public/
│  │  ├─ package.json
│  │  └─ vite.config.ts
│  │
│  └─ backend/
│     ├─ src/
│     │  ├─ truefit_api/                       # HTTP + WebSocket transport layer
│     │  │  ├─ main.py                         # FastAPI app factory
│     │  │  ├─ dependencies.py                 # Dependency injection
│     │  │  └─ api/v1/
│     │  │     ├─ router.py
│     │  │     ├─ http/                        # REST endpoints
│     │  │     │  ├─ jobs.py
│     │  │     │  ├─ candidates.py
│     │  │     │  ├─ interviews.py
│     │  │     │  └─ evaluations.py
│     │  │     └─ ws/
│     │  │        └─ interview.py              # WebSocket interview sessions
│     │  │
│     │  ├─ truefit_core/                      # Domain & application logic
│     │  │  ├─ common/
│     │  │  │  ├─ utils.py
│     │  │  │  └─ exceptions.py
│     │  │  ├─ domain/                         # Domain models
│     │  │  │  ├─ job.py
│     │  │  │  ├─ candidate.py
│     │  │  │  ├─ interview.py
│     │  │  │  └─ evaluation.py
│     │  │  ├─ application/                    # Use cases & services
│     │  │  │  ├─ ports.py
│     │  │  │  ├─ commands/
│     │  │  │  ├─ query/
│     │  │  │  └─ services/
│     │  │  └─ agents/                         # AI agent logic
│     │  │     └─ interviewer/
│     │  │        ├─ prompts.py
│     │  │        ├─ tools.py
│     │  │        └─ context.py
│     │  │
│     │  ├─ truefit_infra/                     # Infrastructure & adapters
│     │  │  ├─ config.py
│     │  │  ├─ container.py                    # Dependency container
│     │  │  ├─ db/
│     │  │  │  ├─ models/
│     │  │  │  ├─ repositories/
│     │  │  │  └─ alembic/
│     │  │  ├─ agent/
│     │  │  ├─ auth/
│     │  │  ├─ cache/
│     │  │  ├─ llm/
│     │  │  ├─ queue/
│     │  │  ├─ realtime/
│     │  │  └─ storage/
│     │  │
│     │  └─ truefit_workers/                   # Background workers
│     │     ├─ evaluation_worker.py
│     │     └─ report_worker.py
│     │
│     ├─ tests/
│     │  ├─ unit/                             # Pure logic tests
│     │  ├─ integration/                      # Database & adapter tests
│     │  └─ e2e/                              # End-to-end workflows
│     │
│     ├─ pyproject.toml
│     ├─ alembic.ini
│     └─ .env.example
```
