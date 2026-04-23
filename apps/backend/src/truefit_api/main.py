from fastapi import FastAPI
import sqlalchemy
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from contextlib import asynccontextmanager

load_dotenv()
from src.truefit_infra.config import AppConfig
from src.truefit_infra.db.database import db_manager
from src.truefit_api.middlewares import (
    register_error_handler,
    req_res_time_log_middleware,
)
from src.truefit_core.common.utils import logger
from src.truefit_api.api.v1.http.health import health_router
from src.truefit_api.api.v1.http.auth import router as auth_router
from src.truefit_api.api.v1.http.jobs import router as jobs_router
from src.truefit_api.api.v1.http.candidates import router as candidates_router
from src.truefit_api.api.v1.http.interviews import router as interviews_router
from src.truefit_api.api.v1.http.orgs import router as orgs_router
from src.truefit_api.api.v1.http.users import router as users_router
from src.truefit_api.api.v1.ws.interview_websocket import interview_ws_router
from src.truefit_api.api.v1.http.applications import router as applications_router
from src.truefit_api.api.v1.http.turn import router as turn_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the lifespan of the Truefit API. It
    initializes the initializes the database manager which
    manages data on server wake up and cleanly closes it on
    shutdown
    """
    try:
        # Initialize database
        engine_kwargs = {}
        if "sqlite" in AppConfig.DATABASE_URL:
            engine_kwargs.update(
                {
                    "connect_args": {"check_same_thread": False},
                    "poolclass": sqlalchemy.StaticPool,
                }
            )
        else:
            engine_kwargs.update(
                {
                    "connect_args": {"statement_cache_size": 0},
                }
            )

        db_manager.initialize(AppConfig.DATABASE_URL, **engine_kwargs)

        # # Create tables
        await db_manager.create_tables()

        logger.info("Application startup complete")
        yield
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    finally:
        # Shutdown
        await db_manager.close()
        logger.info("Application shutdown complete")


app = FastAPI(
    title=AppConfig.PROJECT_NAME, 
    docs_url="/api/docs", 
    openapi_url="/api/openapi.json",
    swagger_ui_parameters={"url": "/api/openapi.json"},
    lifespan=lifespan
)


# Middleware
app.add_middleware(BaseHTTPMiddleware, dispatch=req_res_time_log_middleware)
register_error_handler(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://136.112.82.200",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "*"
    ],  # TODO : Update request headers coming from all whitelisted clients
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(orgs_router, prefix="/api/v1")
app.include_router(candidates_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(interviews_router, prefix="/api/v1")
app.include_router(applications_router, prefix="/api/v1")
app.include_router(interview_ws_router)
app.include_router(turn_router, prefix="/api/v1")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", reload=True, port=8000)
