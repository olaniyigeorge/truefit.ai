from typing import Any, Awaitable, Callable
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time

from src.truefit_core.common.utils import logger


async def req_res_time_log_middleware(request: Request, call_next):
    if request.scope["type"] == "websocket":
        return await call_next(request)

    start_time = time.time()
    response = await call_next(request)
    req_process_time = round((time.time() - start_time) * 1000, 3)

    log_obj = {
        "PATH": request.url.path,
        "METHOD": request.method,
        "STATUS_CODE": response.status_code,
        "REQ/RES_TIME": f"{req_process_time}ms",
    }
    logger.info(log_obj, extra=log_obj)
    return response


# TODO: Debug or re-implement rate limiting middleware
# # ----- Rate Limiting Middleware -----
# async def identifier(request: Request) -> str:
#   ip = request.client.host
#   return ip

# async def _default_callback(request: Request):
#     raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="request limit reached")

# class RateLimitMiddleware:
#     def __init__(
#         self,
#         callback: Callable[[Request], Awaitable[Any]],
#         rate_provider: Callable[[Request], Awaitable[int]],
#         identifier: Callable[[Request], Awaitable[str]] = identifier,
#     ):
#         self.identifier = identifier
#         self.callback = callback
#         self.rate_provider = rate_provider

#     async def __call__(self, request: Request):
#         callback = self.callback
#         identifier = self.identifier
#         rate_provider = self.rate_provider

#         key = await identifier(request)
#         rate = await rate_provider(request)

#         if not hit(key=key, rate_per_minute=rate):
#             return await callback(request)


# async def rate_provider(request: Request) -> str:
#   return 1000


# rate_limit = RateLimitMiddleware(
#     callback=_default_callback,
#     rate_provider=rate_provider
# )


def register_error_handler(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": False,
                "error": exc.detail,
                "path": str(request.url),
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "status": False,
                "error": str(exc),
                "path": str(request.url),
            },
        )
