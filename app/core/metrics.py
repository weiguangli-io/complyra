import time
from typing import Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.services.queue import get_redis_connection

# ── HTTP Metrics ──────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
INGEST_QUEUE_DEPTH = Gauge(
    "ingest_queue_depth",
    "Current depth of the ingest queue",
)

# ── LLM Metrics ───────────────────────────────────────────────────

LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds",
    "LLM call latency in seconds",
    ["provider", "operation"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
LLM_CALL_ERRORS = Counter(
    "llm_call_errors_total",
    "Total LLM call errors",
    ["provider", "operation"],
)
LLM_TOKENS_GENERATED = Counter(
    "llm_tokens_generated_total",
    "Approximate number of LLM tokens generated (streaming chunks)",
    ["provider"],
)

# ── Embedding Metrics ─────────────────────────────────────────────

EMBEDDING_DURATION = Histogram(
    "embedding_duration_seconds",
    "Embedding call latency in seconds",
    ["provider"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
EMBEDDING_TEXTS_PROCESSED = Counter(
    "embedding_texts_processed_total",
    "Total number of texts embedded",
    ["provider"],
)

# ── RAG Pipeline Metrics ─────────────────────────────────────────

RAG_QUERY_TOTAL = Counter(
    "rag_query_total",
    "Total RAG queries processed",
    ["status"],
)
RAG_QUERY_DURATION = Histogram(
    "rag_query_duration_seconds",
    "End-to-end RAG query duration in seconds",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)
RETRIEVAL_DURATION = Histogram(
    "retrieval_duration_seconds",
    "Vector search duration in seconds",
    ["search_type"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
RETRIEVAL_RESULTS_COUNT = Histogram(
    "retrieval_results_count",
    "Number of chunks returned per search",
    buckets=(0, 1, 2, 3, 4, 5, 10, 20),
)

# ── Ingestion Metrics ────────────────────────────────────────────

DOCUMENT_INGEST_TOTAL = Counter(
    "document_ingest_total",
    "Total documents ingested",
    ["file_type", "status"],
)
DOCUMENT_INGEST_DURATION = Histogram(
    "document_ingest_duration_seconds",
    "Document ingestion duration in seconds",
    ["file_type"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
CHUNKS_PRODUCED_TOTAL = Counter(
    "chunks_produced_total",
    "Total number of chunks produced during ingestion",
)

# ── Policy & Approval Metrics ────────────────────────────────────

POLICY_EVALUATIONS_TOTAL = Counter(
    "policy_evaluations_total",
    "Total output policy evaluations",
    ["result"],
)
APPROVAL_REQUESTS_TOTAL = Counter(
    "approval_requests_total",
    "Total approval requests created",
)

# ── System Metrics ───────────────────────────────────────────────

ACTIVE_TENANTS = Gauge(
    "active_tenants",
    "Number of active tenants (from recent queries)",
)
HEALTH_CHECK_STATUS = Gauge(
    "health_check_status",
    "Health check status (1=healthy, 0=unhealthy)",
    ["component"],
)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    if route and hasattr(route, "path"):
        return route.path
    return request.url.path


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        path = _route_path(request)
        method = request.method
        status = str(response.status_code)

        REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
        REQUEST_LATENCY.labels(method=method, path=path).observe(duration)

        return response


def metrics_response() -> Response:
    try:
        redis_conn = get_redis_connection()
        queue_depth = redis_conn.llen(f"rq:queue:{settings.ingest_queue_name}")
        INGEST_QUEUE_DEPTH.set(queue_depth)
    except Exception:
        # Metrics endpoint should stay available even if Redis is unavailable.
        pass

    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
