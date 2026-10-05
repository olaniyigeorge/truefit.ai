.PHONY: dev dev-backend dev-frontend setup soro-test soro-smoke soro-testpypi

## Run backend + frontend together in dev mode
dev:
	@bash scripts/dev.sh

## Run only the backend (bootstraps venv if missing)
dev-backend:
	@[ -d examples/truefit/backend/.venv ] || (python3 -m venv examples/truefit/backend/.venv && cd examples/truefit/backend && .venv/bin/pip install -r requirements.txt)
	@[ -f examples/truefit/backend/.env ] || cp examples/truefit/backend/env.example examples/truefit/backend/.env
	@cd examples/truefit/backend && .venv/bin/python run.py

## Run only the frontend (bootstraps deps if missing)
dev-frontend:
	@[ -d examples/truefit/frontend/node_modules ] || (cd examples/truefit/frontend && pnpm install)
	@[ -f examples/truefit/frontend/.env ] || cp examples/truefit/frontend/env.example examples/truefit/frontend/.env
	@cd examples/truefit/frontend && pnpm dev

## Bootstrap both apps without starting them
setup:
	@python3 -m venv examples/truefit/backend/.venv
	@examples/truefit/backend/.venv/bin/pip install --upgrade pip -q
	@cd examples/truefit/backend && .venv/bin/pip install -r requirements.txt
	@[ -f examples/truefit/backend/.env ] || cp examples/truefit/backend/env.example examples/truefit/backend/.env
	@cd examples/truefit/frontend && pnpm install
	@[ -f examples/truefit/frontend/.env ] || cp examples/truefit/frontend/env.example examples/truefit/frontend/.env

## Run the Soro SDK unit tests
soro-test:
	@cd packages/soro && ../../examples/truefit/backend/.venv/bin/python -m pytest tests -q

## Build Soro, install the wheel into a clean venv and smoke test it (no upload, no keys)
soro-smoke:
	@cd packages/soro && EXTRAS=$${EXTRAS:-gemini,openai,webrtc,vad,openapi,mcp} scripts/test_from_testpypi.sh local

## Install a version already uploaded to TestPyPI and smoke test it: make soro-testpypi VERSION=0.1.0
soro-testpypi:
	@[ -n "$(VERSION)" ] || (echo "usage: make soro-testpypi VERSION=0.1.0"; exit 1)
	@cd packages/soro && EXTRAS=$${EXTRAS:-gemini,openai,webrtc,vad,openapi,mcp} scripts/test_from_testpypi.sh testpypi $(VERSION)
