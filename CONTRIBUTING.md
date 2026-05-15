# Contributing to TrueFit.ai

Thanks for your interest in contributing. TrueFit.ai is an open source project — this document covers everything you need to go from zero to your first pull request.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Prerequisites](#prerequisites)
- [Local Setup](#local-setup)
- [Running the App](#running-the-app)
- [Project Structure](#project-structure)
- [How to Contribute](#how-to-contribute)
- [Code Conventions](#code-conventions)
- [Testing](#testing)
- [Submitting a PR](#submitting-a-pr)
- [Good First Issues](#good-first-issues)

---

## Project Overview

TrueFit.ai automates the first round of hiring by running real-time AI voice interviews via WebRTC, evaluating candidates using structured criteria through Gemini Live API, and delivering reports to recruiters.

**Core flow:**
1. Recruiter creates a job listing with skill requirements and interview config
2. Candidate joins an interview session via a WebRTC-enabled browser session
3. The AI agent (Gemini Live) conducts the interview in real time, adapting questions based on responses
4. After the session, a background worker generates a structured evaluation and recommendation

**Tech stack:**
- Backend: Python · FastAPI · SQLAlchemy · Alembic · PostgreSQL · Redis · aiortc
- Frontend: TypeScript · React · Vite · Tailwind CSS
- AI: Google Gemini Live API
- Real-time: WebRTC · WebSocket
- Auth: Firebase OAuth · JWT
- Infrastructure: GCP Compute Engine · GitHub Actions

---

## Prerequisites

Make sure you have the following installed before starting:

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | Use pyenv or system package manager |
| Node.js | 18+ | Required for frontend |
| pnpm | 10+ | `npm install -g pnpm` |
| PostgreSQL | 14+ | Local instance or Docker |
| Redis | 7+ | Local instance or Docker |
| Git | any | |

**Optional but recommended:**
- Docker (for running Postgres + Redis without local install)
- VSCode with the Python and ESLint extensions

---

## Local Setup

### 1. Fork and clone

```bash
git clone https://github.com/your-org/truefit.ai.git
cd truefit.ai
```

### 2. Backend setup

```bash
cd apps/backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/truefit_db

# Auth
APP_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
FIREBASE_PROJECT_ID=your-firebase-project-id
GOOGLE_APPLICATION_CREDENTIALS=path/to/firebase-service-account.json

# Redis
REDIS_URL=redis://localhost:6379

# Gemini
GEMINI_API_KEY=your-gemini-api-key
```

### 3. Database setup

```bash
# Create the database (if it doesn't exist)
createdb truefit_db

# Run migrations
alembic upgrade head
```

### 4. Frontend setup

```bash
cd apps/frontend
pnpm install
cp env.example .env
```

Open `.env` and set:

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_FIREBASE_API_KEY=your-firebase-api-key
VITE_FIREBASE_PROJECT_ID=your-firebase-project-id
```

---

## Running the App

### Backend

```bash
cd apps/backend
source .venv/bin/activate
python run.py
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/api/docs`

### Frontend

```bash
cd apps/frontend
pnpm dev
```

The frontend will be available at `http://localhost:5173`.

### Monorepo scripts (from root)

```bash
# Run frontend
pnpm dev:fe

# Run backend (Linux/macOS)
pnpm dev:be
```

---

## Project Structure

The backend follows a layered architecture. Understanding this will help you find where things live:

```
truefit_api/        → Transport layer: HTTP routes, WebSocket handlers, request/response schemas
truefit_core/       → Business logic: domain models, services, use cases, AI agent logic
truefit_infra/      → Infrastructure: database, auth, Gemini adapter, WebRTC, Redis, storage
truefit_workers/    → Background workers: evaluation generation, report delivery
```

**Key files to know:**

| File | What it does |
|------|-------------|
| `truefit_api/main.py` | FastAPI app factory, middleware, router registration |
| `truefit_api/dependencies.py` | Dependency injection wiring |
| `truefit_api/api/v1/ws/interview.py` | WebSocket endpoint for live interview sessions |
| `truefit_core/agents/interviewer/` | AI agent prompts, tools, and context management |
| `truefit_infra/realtime/webrtc_client.py` | WebRTC peer connection and audio pipeline |
| `truefit_infra/llm/gemini_live.py` | Gemini Live API adapter |
| `truefit_infra/auth/middleware.py` | JWT validation dependency |

---

## How to Contribute

### Picking up an issue

1. Browse [open issues](https://github.com/your-org/truefit.ai/issues) and look for ones tagged `good first issue` or `help wanted`
2. Comment on the issue to let others know you're working on it
3. If you have a new idea or found a bug, open an issue first before starting work — this avoids duplicated effort

### Branch naming

```
feat/short-description       # new feature
fix/short-description        # bug fix
chore/short-description      # maintenance, deps, config
docs/short-description       # documentation only
```

### Workflow

```bash
# Create your branch from main
git checkout -b feat/your-feature-name

# Make your changes, then commit
git add .
git commit -m "feat: add evaluation score breakdown endpoint"

# Push and open a PR
git push origin feat/your-feature-name
```

---

## Code Conventions

### Backend (Python)

- Formatter: `black` — run `black src/` before committing
- Linter: `flake8` — run `flake8 src/`
- Type hints: required on all function signatures
- Docstrings: include on all public classes and non-trivial functions
- Async: all I/O-bound operations must be `async`

```python
# Good
async def get_interview_session(session_id: UUID) -> InterviewSession:
    """Fetch a session by ID, raising SessionNotFound if it doesn't exist."""
    session = await self.repo.find_by_id(session_id)
    if not session:
        raise SessionNotFound(session_id)
    return session
```

### Frontend (TypeScript)

- Formatter: Prettier (runs on save via VSCode config)
- Linter: ESLint
- Components: functional components only, hooks for state and side effects
- Exports: named exports preferred over default exports for components
- Types: no `any` — define proper interfaces or use generics

```typescript
// Good
interface InterviewSessionProps {
  sessionId: string;
  onEnd: () => void;
}

export const InterviewSession = ({ sessionId, onEnd }: InterviewSessionProps) => {
  // ...
};
```

### Commit message format

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification, inspired by [Angular's commit guidelines](https://github.com/angular/angular/blob/main/CONTRIBUTING.md#-commit-message-format) and [BullMQ's contributing guide](https://github.com/taskforcesh/bullmq/blob/master/contributing.md).

**Format:**
```
<type>(<scope>): <short summary>
```

**Type** must be one of:

| Type | When to use |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation changes only |
| `refactor` | Code change that's neither a fix nor a feature |
| `test` | Adding or updating tests |
| `chore` | Build process, dependency updates, config changes |
| `perf` | Performance improvement |

**Scope** is optional but encouraged — use the module or area you're touching:

```
feat(interviews): add evaluation score breakdown endpoint
fix(webrtc): resolve audio loop on session reconnect
docs(auth): update Firebase setup instructions
chore(deps): upgrade aiortc to 1.9.0
test(jobs): add integration test for job creation endpoint
refactor(agent): extract turn detection into separate class
```

**Rules:**
- Summary is lowercase, no period at the end
- Use the imperative mood: "add" not "added", "fix" not "fixes"
- Keep the summary under 72 characters
- If the change is breaking, add `!` after the type: `feat(auth)!: remove legacy token endpoint`

**Bad examples:**
```
Fixed the bug
Updated stuff
WIP
feat: Added new feature.
```

---

## Testing

### Backend

```bash
cd apps/backend
source .venv/bin/activate

# Run all tests
pytest tests/

# Run by category
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/

# Run with coverage
pytest --cov=src tests/
```

Tests use SQLite for unit/integration tests so you don't need a running Postgres instance for most work. E2E tests require the full stack.

### Frontend

```bash
cd apps/frontend
pnpm test
```

### What to test

- New endpoints: add at least one happy-path and one error-path integration test
- New services/domain logic: add unit tests
- Bug fixes: add a test that would have caught the bug

---

## Submitting a PR

1. Make sure tests pass locally before opening the PR
2. Run linting: `black src/ && flake8 src/` (backend) or `pnpm lint` (frontend)
3. Write a clear PR description — what changed and why
4. Reference the issue your PR closes: `Closes #42`
5. Keep PRs focused — one concern per PR makes reviews faster

The project owner will review and merge. Expect feedback; it's part of the process.

---

## Good First Issues

If you're new to the codebase, these are good places to start:

**Backend:**
- Add pagination to any endpoint that's missing it
- Write missing unit tests for existing services
- Add request validation to an unvalidated endpoint

**Frontend:**
- Improve error state handling in the interview room UI
- Add loading skeletons to data-fetching pages
- Improve mobile responsiveness of the recruiter dashboard

**Docs:**
- Fix outdated code examples
- Add a sequence diagram for the evaluation flow
- Write a guide for setting up Firebase locally

---

## Questions?

Open a GitHub issue tagged `question`, or reach out directly: **olaniyigeorge77@gmail.com**