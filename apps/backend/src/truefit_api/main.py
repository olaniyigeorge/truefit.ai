from fastapi import FastAPI
import sqlalchemy
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from fastapi.responses import HTMLResponse, JSONResponse
# from fastapi.templating import Jinja2Templates
# from fastapi.staticfiles import StaticFiles
from fastapi import Request
from dotenv import load_dotenv
from contextlib import asynccontextmanager

load_dotenv()
from config import AppConfig
from src.truefit_infra.db.database import db_manager 
from src.truefit_api.middlewares import register_error_handler, req_res_time_log_middleware
from src.truefit_core.common.utils import logger

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
# app.add_middleware(BaseHTTPMiddleware, dispatch=log_ip_middleware)
# app.add_middleware(RequestResponseMiddleware)

register_error_handler(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[AppConfig.CLIENT_DOMAIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # TODO : Update request headers coming from all whitelisted clients
)

# templates = Jinja2Templates(directory="src/templates")

# app.mount("/static", StaticFiles(directory="src/static"), name="static")


# app.include_router(auth_router)


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


@app.get("/ping")
async def home(request: Request):  # , rate_limiter = Depends(RateLimitMiddleware())
    return {
        "message": "Pong"
    }

# Health check endpoint for Render
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "revela-backend-api"
        }
    )

# Add HEAD handler for health checks
@app.head("/health")
async def health_check_head():
    return JSONResponse(status_code=200, content={})

@app.head("/")
async def root_head():
    return JSONResponse(status_code=200, content={})




if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        reload=True, 
        port=8000
    )

