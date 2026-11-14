"""FastAPI application factory for the CAMserv platform."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from camserv.api.routes import router as api_v1_router
from camserv.config.settings import CamservSettings
from camserv.security.audit import AuditLogger
from camserv.security.auth import AuthManager, Role, hash_password
from camserv.security.encryption import EncryptionManager
from camserv.storage.evidence import EvidenceStore
from camserv.storage.milvus_store import MilvusStore
from camserv.storage.redis_cache import RedisCache

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for connection pooling, background tasks, and clean teardown."""
    logger.info("camserv.starting_up", version="0.1.0")

    # Connect Redis
    redis_cache: RedisCache | None = getattr(app.state, "redis_cache", None)
    if redis_cache is not None:
        await redis_cache.connect()

    # Connect Milvus
    milvus_store: MilvusStore | None = getattr(app.state, "milvus_store", None)
    if milvus_store is not None:
        await milvus_store.connect()

    yield

    # Teardown
    logger.info("camserv.shutting_down")
    if redis_cache is not None:
        await redis_cache.close()
    if milvus_store is not None:
        await milvus_store.close()


def create_app(settings: CamservSettings | None = None) -> FastAPI:
    """Create and configure a production-ready FastAPI application instance."""
    app = FastAPI(
        title="CAMserv API",
        description=(
            "Advanced Security Intelligence Platform — real-time video analytics, "
            "tamper-evident evidence storage, and privacy-preserving AI inference."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ---------------------------------------------------------------------------
    # Initialise Subsystems and State
    # ---------------------------------------------------------------------------
    # Load master key or fallback
    master_key = os.environ.get("CAMSERV_MASTER_KEY")
    if not master_key:
        master_key = EncryptionManager.generate_master_key()
        os.environ["CAMSERV_MASTER_KEY"] = master_key

    crypto = EncryptionManager(master_key=master_key)
    app.state.crypto = crypto

    # AuthManager
    jwt_secret = "camserv-default-jwt-secret-key-at-least-32-chars-long"
    if settings is not None and hasattr(settings, "security") and settings.security.jwt.secret_key:
        jwt_secret = settings.security.jwt.secret_key.get_secret_value()

    auth = AuthManager(secret_key=jwt_secret)
    # Register default administrative user for dev/testing
    admin_hash = hash_password("admin_password")
    auth.add_user("admin", admin_hash, Role.ADMIN)
    viewer_hash = hash_password("viewer_password")
    auth.add_user("viewer", viewer_hash, Role.VIEWER)
    operator_hash = hash_password("operator_password")
    auth.add_user("operator", operator_hash, Role.OPERATOR)
    auditor_hash = hash_password("auditor_password")
    auth.add_user("auditor", auditor_hash, Role.AUDITOR)

    app.state.auth_manager = auth

    # AuditLogger
    env_audit_path = os.environ.get("CAMSERV_SECURITY__AUDIT_LOG_PATH")
    if settings is not None and hasattr(settings, "security") and settings.security.audit_log_path:
        audit_path = settings.security.audit_log_path
    elif env_audit_path:
        audit_path = Path(env_audit_path)
    else:
        audit_path = Path("logs/audit.jsonl")
    audit = AuditLogger(log_path=audit_path)
    app.state.audit_logger = audit

    # Storage subsystems
    redis_settings = settings.storage.redis if settings else None
    redis_cache = RedisCache(
        host=redis_settings.host if redis_settings else "localhost",
        port=redis_settings.port if redis_settings else 6379,
        password=redis_settings.password.get_secret_value() if redis_settings and redis_settings.password else None,
        ssl=redis_settings.ssl if redis_settings else False,
        max_connections=redis_settings.max_connections if redis_settings else 20,
    )
    app.state.redis_cache = redis_cache

    milvus_settings = settings.storage.milvus if settings else None
    milvus_store = MilvusStore(
        host=milvus_settings.host if milvus_settings else "localhost",
        port=milvus_settings.port if milvus_settings else 19530,
        collection_name=milvus_settings.collection if milvus_settings else "camserv_scene_analytics",
        dim=milvus_settings.dim if milvus_settings else 128,
        index_type=milvus_settings.index_type if milvus_settings else "IVF_FLAT",
        metric_type=milvus_settings.metric_type if milvus_settings else "IP",
    )
    app.state.milvus_store = milvus_store

    evidence_dir = Path("data/evidence")
    evidence_store = EvidenceStore(base_dir=evidence_dir, encryption_manager=crypto)
    app.state.evidence_store = evidence_store

    # In-memory repositories for camera CRUD and events if standalone
    app.state.cameras = {}
    app.state.events = []
    app.state.detections = []
    app.state.tracks = []
    app.state.settings = settings

    # ---------------------------------------------------------------------------
    # CORS Configuration
    # ---------------------------------------------------------------------------
    cors_origins = (
        settings.security.cors_origins
        if settings is not None and hasattr(settings, "security")
        else ["*"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if "*" not in cors_origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------------------
    # Exception Handlers
    # ---------------------------------------------------------------------------
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        logger.warning("api.validation_error", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Invalid request: {str(exc)}"},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("api.unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error. Incident has been logged."},
        )

    # ---------------------------------------------------------------------------
    # Root Health Check & Router Mounting
    # ---------------------------------------------------------------------------
    @app.get("/health", tags=["System"])
    async def root_health() -> dict[str, str]:
        return {"status": "ok", "app": "CAMserv", "version": "0.1.0"}

    app.include_router(api_v1_router)

    # ---------------------------------------------------------------------------
    # Mount CAMserv Enterprise Web Console
    # ---------------------------------------------------------------------------
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        from starlette.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web_console")

    return app
