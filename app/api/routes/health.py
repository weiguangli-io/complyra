from __future__ import annotations

import time

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.metrics import HEALTH_CHECK_STATUS
from app.db.session import SessionLocal
from app.services.retrieval import get_qdrant_client
from app.services.llm import ollama_health
from app.services.queue import get_redis_connection

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live_check():
    return {"status": "ok"}


@router.get("/ready")
def ready_check():
    checks: dict = {}

    # Database
    try:
        t0 = time.perf_counter()
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = {"status": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        checks["database"] = {"status": False, "error": str(exc)[:100]}

    # Qdrant
    try:
        t0 = time.perf_counter()
        qdrant = get_qdrant_client()
        collections = qdrant.get_collections()
        checks["qdrant"] = {
            "status": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "collections": len(collections.collections),
        }
    except Exception as exc:
        checks["qdrant"] = {"status": False, "error": str(exc)[:100]}

    # Redis
    try:
        t0 = time.perf_counter()
        redis_conn = get_redis_connection()
        redis_conn.ping()
        checks["redis"] = {"status": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        checks["redis"] = {"status": False, "error": str(exc)[:100]}

    # LLM provider
    t0 = time.perf_counter()
    llm_ok = ollama_health()
    checks["llm"] = {
        "status": llm_ok,
        "provider": settings.llm_provider,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
    }

    # Update Prometheus gauges
    for component, detail in checks.items():
        HEALTH_CHECK_STATUS.labels(component=component).set(1.0 if detail["status"] else 0.0)

    all_ok = all(c["status"] for c in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "version": "1.0.0",
        "environment": settings.env,
        "llm_provider": settings.llm_provider,
        "embedding_provider": settings.embedding_provider,
        "checks": checks,
    }
