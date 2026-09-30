# Contributing to TrueFit.ai

Thanks for your interest in contributing. This guide takes you from a fresh clone to your first pull request.

## Table of Contents

- [Project overview](#project-overview)
- [Prerequisites](#prerequisites)
- [Local setup](#local-setup)
- [Running the app](#running-the-app)
- [Project structure](#project-structure)
- [How to contribute](#how-to-contribute)
- [Code conventions](#code-conventions)
- [Testing](#testing)
- [Working on the Soro SDK](#working-on-the-soro-sdk)
- [Submitting a PR](#submitting-a-pr)

---

## Project overview

This repository holds two things:

- **Soro** (`packages/soro`), a model-agnostic realtime voice agent SDK. You write an agent once and run it on Gemini Live, OpenAI Realtime or another provider through one interface.
- **TrueFit.ai** (`apps/`), an AI interview product built on Soro. Recruiters create jobs, candidates join a live voice interview over WebRTC, and the platform produces a structured evaluation.

**Tech stack**

- Backend: Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, aiortc
- Frontend: TypeScript, React, Vite, Tailwind CSS
- Voice: Soro, with Gemini Live and OpenAI Realtime adapters
- Real-time: WebRTC and WebSocket
- Auth: Firebase OAuth and JWT
- Infrastructure: GCP Compute Engine, GitHub Actions

See [docs/architecture.md](./docs/architecture.md) for how the pieces fit together and [docs/api.md](./docs/api.md) for the API.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ (3.12 recommended) | pyenv or your system package manager |
| Node.js | 18+ | Frontend |
| pnpm | 10+ | `npm install -g pnpm` |
| PostgreSQL | 14+ | Local instance or Docker |
| Redis | 7+ | Local instance or Docker |
| make | any | Wraps the common commands |
| Git | any | |

Optional: Docker for Postgres and Redis, and VS Code with the Python and ESLint extensions. The repo ships `.vscode/settings.json`, which points Python at `apps/backend/.venv` and enables pytest. On Windows, change the interpreter path to `apps/backend/.venv/Scripts/python.exe`.

---

## Local setup

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/truefit.ai.git
cd truefit.ai
```

### 2. One-command setup

```bash
make setup
```

This creates `apps/backend/.venv`, installs the backend requirements (which include the local `packages/soro[all]` in editable mode), runs `pnpm install` for the frontend, and copies `env.example` to `.env` in both apps if they are missing.

### 3. Configure the backend

Edit `apps/backend/.env`. The important values:

```env
# Database and cache
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/truefit_db
REDIS_URL=redis://localhost:6379/0

# Auth
APP_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
FIREBASE_PROJECT_ID=your-firebase-project-id

# Voice provider (gemini or openai, optional fallback)
LLM_PRIMARY_PROVIDER=gemini
LLM_FALLBACK_PROVIDER=none
GEMINI_API_KEY=your-gemini-api-key
OPENAI_API_KEY=                     # only if OpenAI is primary or fallback
```

`apps/backend/env.example` lists every setting with comments. The unit and integration tests need none of these.

### 4. Create the database

```bash
createdb truefit_db
```

The app creates its tables on startup. See [docs/architecture.md](./docs/architecture.md) for the state of the Alembic migrations before you rely on them.

### 5. Configure the frontend

Edit `apps/frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_FIREBASE_API_KEY=your-firebase-api-key
VITE_FIREBASE_PROJECT_ID=your-firebase-project-id
```

---

## Running the app

```bash
make dev             # backend (port 8000) and frontend (port 5173) together
make dev-backend     # backend only
make dev-frontend    # frontend only
```

Interactive API docs are at `http://localhost:8000/api/docs` while the backend runs.

---

## Project structure

```
packages/soro/       The Soro SDK (publishable on its own, depends on no app code)
apps/backend/        FastAPI interview backend
apps/frontend/       React + Vite interview UI
docs/                Architecture, API, project story, pivot plan
scripts/             dev.sh, deploy.sh, setup-gcp.sh
```

The backend is layered. Knowing the layers tells you where code belongs:

```
truefit_api/        Transport: HTTP routes, WebSocket handlers, schemas
truefit_core/       Domain models, services, use cases, interview agent logic (no infra imports)
truefit_infra/      Adapters: database, auth, Redis, WebRTC signaling, Soro factory
truefit_workers/    Background workers (placeholders today)
```

A test enforces that `truefit_core` never imports `truefit_infra`.

**Key files**

| File | What it does |
|------|-------------|
| `apps/backend/src/truefit_api/main.py` | FastAPI app, middleware, router registration |
| `apps/backend/src/truefit_api/dependencies.py` | Dependency injection wiring |
| `apps/backend/src/truefit_api/api/v1/ws/interview_websocket.py` | WebSocket endpoint for live interviews |
| `apps/backend/src/truefit_core/agents/interviewer/` | Interview prompt, tools, handlers and agent |
| `apps/backend/src/truefit_infra/realtime/webrtc_client.py` | WebRTC peer connection |
| `apps/backend/src/truefit_infra/llm/factory.py` | Feeds app settings to Soro's adapter factory |
| `apps/backend/src/truefit_infra/auth/middleware.py` | JWT validation dependency |
| `packages/soro/src/soro/ports.py` | The `LiveSessionPort` interface every provider implements |
| `packages/soro/src/soro/transport/webrtc.py` | WebRTC audio bridge and turn handling |

---

## How to contribute

### Picking up an issue

1. Browse [open issues](https://github.com/olaniyigeorge/truefit.ai/issues) for `good first issue` or `help wanted`.
2. Comment on the issue so others know you are working on it.
3. For a new idea or a bug, open an issue first to avoid duplicated effort.

### Branch naming

```
feat/short-description       # new feature
fix/short-description        # bug fix
chore/short-description      # maintenance, deps, config
docs/short-description       # documentation only
```

### Workflow

```bash
git checkout -b feat/your-feature-name
# make your changes
git commit -m "feat(interviews): add evaluation score breakdown endpoint"
git push origin feat/your-feature-name
```

Then open a pull request against `main`.

---

## Code conventions

### Backend (Python)

- Formatter: `black`. Install it with `pip install black` and run `black apps/backend/src packages/soro/src` before committing.
- Type hints on all function signatures.
- Docstrings on public classes and non-trivial functions.
- All I/O-bound operations are `async`.

```python
async def get_interview_session(session_id: UUID) -> InterviewSession:
    """Fetch a session by ID, raising SessionNotFound if it does not exist."""
    session = await self.repo.find_by_id(session_id)
    if not session:
        raise SessionNotFound(session_id)
    return session
```

### Frontend (TypeScript)

- Linter: ESLint (`pnpm lint` in `apps/frontend`).
- Functional components with hooks; named exports preferred.
- No `any`: define interfaces or use generics.

### Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/).

```
<type>(<scope>): <short summary>
```

| Type | When to use |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `refactor` | Neither a fix nor a feature |
| `test` | Adding or updating tests |
| `chore` | Build, dependencies, config |
| `perf` | Performance improvement |

The scope is optional. Useful ones: `soro`, `interviews`, `auth`, `webrtc`, `agent`, `deps`.

```
feat(soro): add pluggable turn detection
fix(webrtc): resolve audio loop on session reconnect
docs(api): document the turn credentials endpoint
```

Rules: lowercase summary with no trailing period, imperative mood ("add", not "added"), under 72 characters, and `!` after the type for breaking changes (`feat(auth)!: remove legacy token endpoint`).

---

## Testing

```bash
make soro-test                               # the Soro SDK
cd apps/backend && .venv/bin/python -m pytest tests     # backend: unit and integration
cd apps/backend && .venv/bin/python -m pytest tests/unit   # backend, unit only
cd apps/frontend && pnpm lint && pnpm build     # frontend type check and lint
```

- **Unit tests** use fake providers and need no keys, database or Redis.
- **Integration tests** use in-memory SQLite through `tests/conftest.py`. The models use Postgres-only types (ARRAY, JSONB), so the test fixtures swap them for JSON in the test process only. A behaviour that depends on Postgres itself needs a real database.
- There is no frontend test suite yet.

What to test:

- New endpoints: at least one happy-path and one error-path test.
- New services or domain logic: unit tests.
- Bug fixes: a test that would have caught the bug.

---

## Working on the Soro SDK

Soro lives in `packages/soro` and must not import anything from `apps/`. Install it on its own with `pip install -e "packages/soro[dev]"`.

Before a release, check the package the way a user gets it:

```bash
make soro-smoke                              # build, twine check, clean venv, smoke test
make soro-testpypi VERSION=0.1.0             # after uploading to TestPyPI
```

See [packages/soro/README.md](./packages/soro/README.md) for the release steps.

---

## Submitting a PR

1. Make sure the tests pass locally.
2. Run the formatters and linters that apply to the code you touched.
3. Write a clear description: what changed and why.
4. Reference the issue your PR closes: `Closes #42`.
5. Keep PRs focused. One concern per PR makes review faster.

The project owner reviews and merges. Expect feedback, it is part of the process.
