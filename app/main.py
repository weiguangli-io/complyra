"""FastAPI application factory and startup lifecycle."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.metrics import MetricsMiddleware, metrics_response
from app.core.request_id import RequestIDMiddleware
from app.core.request_logging import RequestLoggingMiddleware
from app.core.security import hash_password
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.audit_db import ensure_default_seed, init_db
from app.services.llm import ensure_model_ready

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    init_db()
    demo_hash = settings.demo_password_hash or hash_password(settings.demo_password or "demo123")
    ensure_default_seed(
        demo_username=settings.demo_username,
        demo_password_hash=demo_hash,
        default_tenant_id=settings.default_tenant_id,
    )
    if not ensure_model_ready():
        logger.warning("Ollama model pre-pull failed. The service will still start, but first requests may fail.")
    yield


def create_app() -> FastAPI:
    setup_logging()

    # Attach in-memory log buffer for admin monitoring dashboard
    from app.core.log_buffer import BufferHandler
    root_logger = logging.getLogger()
    root_logger.addHandler(BufferHandler())

    # Enable LangSmith tracing when configured — sets env vars that LangGraph reads automatically
    if settings.langsmith_tracing and settings.langsmith_api_key:
        import os

        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        logger.info("LangSmith tracing enabled for project '%s'", settings.langsmith_project)

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.1,
        )

    app = FastAPI(title=settings.app_name, lifespan=app_lifespan)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "X-Tenant-ID", "X-Request-ID", "X-Metrics-Token"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    if settings.metrics_enabled:

        @app.get(settings.metrics_path)
        def metrics(x_metrics_token: str | None = Header(default=None, alias="X-Metrics-Token")):
            if settings.metrics_token and x_metrics_token != settings.metrics_token:
                raise HTTPException(status_code=401, detail="Invalid metrics token")
            return metrics_response()

    return app


app = create_app()
