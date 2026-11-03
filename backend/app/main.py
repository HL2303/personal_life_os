import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.activities import router as activities_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.goals import router as goals_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.telegram_settings import router as telegram_settings_router
from app.api.telegram_webhook import router as telegram_webhook_router
from app.core.config import settings

is_production = settings.app_env == "production"
app = FastAPI(
    title="Personal Life OS API",
    version="0.1.0",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(activities_router)
app.include_router(analytics_router)
app.include_router(goals_router)
app.include_router(projects_router)
app.include_router(telegram_settings_router)
app.include_router(telegram_webhook_router)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_request, exc: SQLAlchemyError) -> JSONResponse:
    logging.getLogger(__name__).exception("Database operation failed", exc_info=exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is temporarily unavailable. Please try again."},
    )
