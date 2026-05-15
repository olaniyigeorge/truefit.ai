# TrueFit.ai

TrueFit.ai is a Gemini-powered live AI agent that automates hiring by conducting real-time voice interviews, evaluating candidates on structured criteria, and generating actionable recommendations. Companies create job listings, and candidates start instant AI interview sessions with adaptive questioning and structured evaluation reports.

**Stack:** FastAPI · WebRTC · Gemini Live API · OpenAI Realtime · React · PostgreSQL · Redis

---

## Project Structure

```
truefit.ai/
├── apps/
│   ├── frontend/                     # Vite + React + TypeScript
│   │   ├── src/
│   │   │   ├── components/           # Shared UI components
│   │   │   ├── pages/                # Route-level pages
│   │   │   ├── hooks/                # Custom React hooks
│   │   │   ├── helpers/              # API client, WebSocket, utilities
│   │   │   ├── context/              # React context providers
│   │   │   └── providers/            # App-level providers
│   │   ├── public/
│   │   ├── package.json
│   │   └── vite.config.ts
│   │
│   └── backend/
│       ├── src/
│       │   ├── truefit_api/          # HTTP + WebSocket transport layer
│       │   │   ├── main.py           # FastAPI app factory
│       │   │   ├── dependencies.py   # Dependency injection
│       │   │   └── api/v1/
│       │   │       ├── http/         # REST endpoints
│       │   │       │   ├── auth.py
│       │   │       │   ├── jobs.py
│       │   │       │   ├── candidates.py
│       │   │       │   ├── interviews.py
│       │   │       │   └── evaluations.py
│       │   │       └── ws/
│       │   │           └── interview.py   # WebSocket interview sessions
│       │   │
│       │   ├── truefit_core/         # Domain & application logic
│       │   │   ├── domain/           # Domain models
│       │   │   │   ├── job.py
│       │   │   │   ├── candidate.py
│       │   │   │   ├── interview.py
│       │   │   │   └── evaluation.py
│       │   │   ├── application/      # Use cases & services
│       │   │   │   ├── ports.py
│       │   │   │   ├── commands/
│       │   │   │   ├── query/
│       │   │   │   └── services/
│       │   │   └── agents/           # AI agent logic
│       │   │       └── interviewer/
│       │   │           ├── prompts.py
│       │   │           ├── tools.py
│       │   │           └── context.py
│       │   │
│       │   ├── truefit_infra/        # Infrastructure & adapters
│       │   │   ├── config.py
│       │   │   ├── container.py      # Dependency container
│       │   │   ├── db/               # SQLAlchemy models + repositories
│       │   │   ├── auth/             # JWT + Firebase OAuth
│       │   │   ├── llm/              # Gemini Live adapter
│       │   │   ├── realtime/         # WebRTC client (aiortc)
│       │   │   ├── cache/            # Redis
│       │   │   ├── queue/            # Background job queue
│       │   │   └── storage/          # File storage
│       │   │
│       │   └── truefit_workers/      # Background workers
│       │       ├── evaluation_worker.py
│       │       └── report_worker.py
│       │
│       ├── tests/
│       │   ├── unit/
│       │   ├── integration/
│       │   └── e2e/
│       │
│       ├── alembic/                  # Database migrations
│       ├── alembic.ini
│       ├── requirements.txt
│       └── .env.example
│
├── docs/
│   ├── architecture.md               # System design & component overview
│   ├── api.md                        # REST + WebSocket API reference
│   ├── auth.md                       # OAuth & JWT implementation guide
│   └── webrtc.md                     # Real-time communication deep dive
│
├── scripts/
│   ├── deploy.sh
│   └── setup-gcp.sh
│
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── package.json                      # Monorepo scripts (pnpm)
```

---

## Quick Start

See [CONTRIBUTING.md](./CONTRIBUTING.md) for full setup instructions.

**Prerequisites:** Python 3.11+, Node.js 18+, pnpm, PostgreSQL, Redis

```bash
git clone https://github.com/your-org/truefit.ai.git
cd truefit.ai

# Backend
cd apps/backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # fill in your values
alembic upgrade head
python run.py

# Frontend (new terminal)
cd apps/frontend
pnpm install
cp env.example .env
pnpm dev
```

---

## Documentation

| Doc | Description |
|-----|-------------|
| [docs/architecture.md](./docs/architecture.md) | System design, components, data flow |
| [docs/api.md](./docs/api.md) | REST endpoints, WebSocket events, data models |
| [docs/auth.md](./docs/auth.md) | Firebase OAuth + JWT implementation |
| [docs/webrtc.md](./docs/webrtc.md) | WebRTC + WebSocket real-time architecture |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | How to contribute, local setup, conventions |
| [SECURITY.md](./SECURITY.md) | Vulnerability reporting, secrets management |

Interactive API docs are available at `http://localhost:8000/api/docs` when the backend is running.

---

## Contributing

This is an open source project. Contributions are welcome - see [CONTRIBUTING.md](./CONTRIBUTING.md) to get started.

---

## License

[MIT](./LICENSE)