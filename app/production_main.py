from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import configure_logging, get_settings
from app.database import AsyncSessionLocal, engine
from app.extended_models import DocumentArtifact  # noqa: F401 - registers table metadata
from app.middleware import RequestContextMiddleware
from app.models import Base
from app.routes.document_routes import router as document_router
from app.services.job_recovery import recover_interrupted_jobs

configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.deployment_mode == "local":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        recovered_jobs = await recover_interrupted_jobs(db)
    logger.info(
        "Application startup complete",
        extra={
            "deployment_mode": settings.deployment_mode,
            "recovered_interrupted_jobs": recovered_jobs,
        },
    )
    yield
    await engine.dispose()
    logger.info("Production application shutdown complete")


app = FastAPI(
    title="DocFlow-AI",
    description=(
        "Deterministic multi-format extraction, rule-based classification, "
        "job tracking, metrics, and source-document retrieval."
    ),
    version="3.1.0",
    lifespan=lifespan,
    contact={"name": "Muhammad Ali Nawaz"},
)

app.include_router(document_router)

allow_wildcard = settings.cors_origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=not allow_wildcard,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-DocFlow-Key", settings.request_id_header],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts)
app.add_middleware(
    RequestContextMiddleware,
    request_id_header=settings.request_id_header,
)


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"success": True, "message": "Service is ready", "data": {"database": "ok"}}


@app.get("/about", tags=["metadata"])
async def about() -> dict:
    return {
        "success": True,
        "message": "Project metadata",
        "data": {
            "project": "DocFlow-AI",
            "version": "3.1.0",
            "developer": "Muhammad Ali Nawaz",
            "processing": "deterministic rule-based extraction and classification",
            "deployment_mode": settings.deployment_mode,
        },
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": str(exc.detail),
            "data": {"request_id": request_id},
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    safe_errors = [
        {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": "Validation error",
            "data": {"request_id": request_id, "errors": safe_errors},
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled exception", extra={"request_id": request_id})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "Internal server error",
            "data": {"request_id": request_id},
        },
    )
