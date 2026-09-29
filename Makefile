.PHONY: dev dev-backend dev-frontend setup

## Run backend + frontend together in dev mode
dev:
	@bash scripts/dev.sh

## Run only the backend (bootstraps venv if missing)
dev-backend:
	@[ -d apps/backend/.venv ] || (python3 -m venv apps/backend/.venv && apps/backend/.venv/bin/pip install -r apps/backend/requirements.txt)
	@[ -f apps/backend/.env ] || cp apps/backend/env.example apps/backend/.env
	@cd apps/backend && .venv/bin/python run.py

## Run only the frontend (bootstraps deps if missing)
dev-frontend:
	@[ -d apps/frontend/node_modules ] || (cd apps/frontend && pnpm install)
	@[ -f apps/frontend/.env ] || cp apps/frontend/env.example apps/frontend/.env
	@cd apps/frontend && pnpm dev

## Bootstrap both apps without starting them
setup:
	@python3 -m venv apps/backend/.venv
	@apps/backend/.venv/bin/pip install --upgrade pip -q
	@apps/backend/.venv/bin/pip install -r apps/backend/requirements.txt
	@[ -f apps/backend/.env ] || cp apps/backend/env.example apps/backend/.env
	@cd apps/frontend && pnpm install
	@[ -f apps/frontend/.env ] || cp apps/frontend/env.example apps/frontend/.env
