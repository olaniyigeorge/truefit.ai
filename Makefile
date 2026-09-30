.PHONY: dev dev-backend dev-frontend setup soro-test soro-smoke soro-testpypi

## Run backend + frontend together in dev mode
dev:
	@bash scripts/dev.sh

## Run only the backend (bootstraps venv if missing)
dev-backend:
	@[ -d apps/backend/.venv ] || (python3 -m venv apps/backend/.venv && cd apps/backend && .venv/bin/pip install -r requirements.txt)
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
	@cd apps/backend && .venv/bin/pip install -r requirements.txt
	@[ -f apps/backend/.env ] || cp apps/backend/env.example apps/backend/.env
	@cd apps/frontend && pnpm install
	@[ -f apps/frontend/.env ] || cp apps/frontend/env.example apps/frontend/.env

## Run the Soro SDK unit tests
soro-test:
	@cd packages/soro && ../../apps/backend/.venv/bin/python -m pytest tests -q

## Build Soro, install the wheel into a clean venv and smoke test it (no upload, no keys)
soro-smoke:
	@cd packages/soro && EXTRAS=$${EXTRAS:-gemini,openai,webrtc} scripts/test_from_testpypi.sh local

## Install a version already uploaded to TestPyPI and smoke test it: make soro-testpypi VERSION=0.1.0
soro-testpypi:
	@[ -n "$(VERSION)" ] || (echo "usage: make soro-testpypi VERSION=0.1.0"; exit 1)
	@cd packages/soro && EXTRAS=$${EXTRAS:-gemini,openai,webrtc} scripts/test_from_testpypi.sh testpypi $(VERSION)
