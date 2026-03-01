from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.truefit_infra.db.database import db_manager

health_router = APIRouter(tags=["health"])


async def _check_database() -> Dict[str, Any]:
    try:
        async with db_manager.get_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _check_cache() -> Dict[str, Any]:
    # TODO: wire up cache client check (Redis, etc.)
    # e.g. await cache_client.ping()
    return {"status": "skipped"}


async def _check_llm() -> Dict[str, Any]:
    # TODO: wire up truefit_infra LLM check
    # e.g. verify API key is set, client is instantiated, etc.
    return {"status": "skipped"}


async def _check_queues() -> Dict[str, Any]:
    # TODO: wire up truefit_infra queue check
    return {"status": "skipped"}


async def _check_storage() -> Dict[str, Any]:
    # TODO: wire up truefit_infra storage check
    return {"status": "skipped"}


@health_router.get("/health", include_in_schema=False)
async def health_check() -> JSONResponse:
    """
    Health endpoint. Checks all internal dependencies directly — no HTTP round-trips.
    Returns: ok | degraded | down
    """
    started = time.perf_counter()

    checks: Dict[str, Any] = {}

    checks["database"] = await _check_database()
    checks["cache"] = await _check_cache()
    checks["llm"] = await _check_llm()
    checks["queues"] = await _check_queues()
    checks["storage"] = await _check_storage()

    down = [k for k, v in checks.items() if v["status"] == "down"]
    skipped = [k for k, v in checks.items() if v["status"] == "skipped"]

    if len(down) == len(checks):
        overall = "down"
    elif down:
        overall = "degraded"
    else:
        overall = "ok"

    latency_ms = int((time.perf_counter() - started) * 1000)

    payload = {
        "status": overall,
        "service": "truefit-backend-api",
        "latency_ms": latency_ms,
        "checks": checks,
        **({"skipped": skipped} if skipped else {}),
    }

    http_status = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if overall == "down"
        else status.HTTP_200_OK
    )
    return JSONResponse(status_code=http_status, content=payload)


@health_router.get("/", include_in_schema=False)
async def root() -> Dict[str, str]:
    return {"status": "ok"}