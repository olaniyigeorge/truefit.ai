from fastapi import FastAPI
import sqlalchemy
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from contextlib import asynccontextmanager

load_dotenv()
from truefit_infra.config import AppConfig
from src.truefit_infra.db.database import db_manager 
from src.truefit_api.middlewares import register_error_handler, req_res_time_log_middleware
from src.truefit_core.common.utils import logger
from truefit_api.api.v1.http.health import health_router

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


app = FastAPI(title=AppConfig.PROJECT_NAME, docs_url="/api/docs", lifespan=lifespan)


# Middleware
app.add_middleware(BaseHTTPMiddleware, dispatch=req_res_time_log_middleware)
register_error_handler(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[AppConfig.CLIENT_DOMAIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # TODO : Update request headers coming from all whitelisted clients
)

app.include_router(health_router)


# @app.get("/", response_class=HTMLResponse)
# async def home(request: Request):
#     base_url = AppConfig.DOMAIN
#     # TODO : Version documentation

#     return templates.TemplateResponse(
#         request,
#         "home.html",
#         {
#             "name": "Revele Backend",
#             "details": "Revela API Backend",
#             "docs": f"api/docs",
#         },
#     )





if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        reload=True, 
        port=8000
    )

