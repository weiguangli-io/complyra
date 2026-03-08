"""Admin monitoring API endpoints.

Provides metrics summary, application logs, and system health
data for the built-in monitoring dashboard.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, Query
from prometheus_client import REGISTRY

from app.api.deps import get_current_user, require_roles
from app.core.log_buffer import get_log_buffer

router = APIRouter(
    prefix="/admin/monitoring",
    tags=["monitoring"],
    dependencies=[Depends(require_roles(["admin"]))],
)


def _get_metric_value(name: str, labels: dict | None = None) -> float:
    """Read a single metric value from the Prometheus registry."""
    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                if labels is None:
                    return sample.value
                if all(sample.labels.get(k) == v for k, v in labels.items()):
                    return sample.value
    return 0.0


def _get_metric_sum(name: str, label_key: str | None = None) -> float:
    """Sum all samples of a metric, optionally grouping."""
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                if sample.name == name or sample.name == f"{name}_total":
                    total += sample.value
    return total


def _get_histogram_stats(name: str) -> dict:
    """Extract count, sum, avg from a histogram metric."""
    count = 0.0
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                if sample.name == f"{name}_count":
                    count += sample.value
                elif sample.name == f"{name}_sum":
                    total += sample.value
    avg = total / count if count > 0 else 0.0
    return {"count": count, "sum": round(total, 3), "avg": round(avg, 3)}


def _get_histogram_by_label(name: str, label: str) -> dict:
    """Get histogram stats grouped by a label."""
    groups: dict[str, dict] = {}
    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                lbl = sample.labels.get(label, "unknown")
                if lbl not in groups:
                    groups[lbl] = {"count": 0.0, "sum": 0.0}
                if sample.name == f"{name}_count":
                    groups[lbl]["count"] += sample.value
                elif sample.name == f"{name}_sum":
                    groups[lbl]["sum"] += sample.value
    result = {}
    for k, v in groups.items():
        avg = v["sum"] / v["count"] if v["count"] > 0 else 0.0
        result[k] = {"count": v["count"], "avg": round(avg, 3)}
    return result


def _get_counter_by_label(name: str, label: str) -> dict:
    """Get counter values grouped by a label."""
    groups: dict[str, float] = {}
    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                if sample.name == name or sample.name == f"{name}_total":
                    lbl = sample.labels.get(label, "unknown")
                    groups[lbl] = groups.get(lbl, 0) + sample.value
    return groups


@router.get("/metrics")
def get_metrics_summary(user: dict = Depends(get_current_user)):
    """Aggregated metrics snapshot for the dashboard."""
    # HTTP metrics
    http_stats = _get_histogram_stats("http_request_duration_seconds")
    http_total = _get_metric_sum("http_requests_total")
    http_by_status = _get_counter_by_label("http_requests_total", "status")
    error_count = sum(v for k, v in http_by_status.items() if k.startswith("5"))

    # LLM metrics
    llm_stats = _get_histogram_stats("llm_call_duration_seconds")
    llm_by_provider = _get_histogram_by_label("llm_call_duration_seconds", "provider")
    llm_errors = _get_metric_sum("llm_call_errors_total")
    llm_tokens = _get_metric_sum("llm_tokens_generated_total")

    # RAG metrics
    rag_stats = _get_histogram_stats("rag_query_duration_seconds")
    rag_by_status = _get_counter_by_label("rag_query_total", "status")

    # Retrieval metrics
    retrieval_stats = _get_histogram_stats("retrieval_duration_seconds")
    retrieval_by_type = _get_histogram_by_label("retrieval_duration_seconds", "search_type")

    # Embedding metrics
    embedding_stats = _get_histogram_stats("embedding_duration_seconds")
    embedding_texts = _get_metric_sum("embedding_texts_processed_total")

    # Ingestion metrics
    ingest_by_status = _get_counter_by_label("document_ingest_total", "status")
    ingest_by_type = _get_counter_by_label("document_ingest_total", "file_type")
    ingest_duration = _get_histogram_stats("document_ingest_duration_seconds")
    chunks_total = _get_metric_sum("chunks_produced_total")
    queue_depth = _get_metric_value("ingest_queue_depth")

    # Policy metrics
    policy_by_result = _get_counter_by_label("policy_evaluations_total", "result")

    # Health metrics
    health: dict[str, float] = {}
    for metric in REGISTRY.collect():
        if metric.name == "health_check_status":
            for sample in metric.samples:
                component = sample.labels.get("component", "")
                if component:
                    health[component] = sample.value

    return {
        "http": {
            "total_requests": http_total,
            "error_count": error_count,
            "error_rate": round(error_count / max(http_total, 1), 4),
            "avg_latency": http_stats["avg"],
            "by_status": http_by_status,
        },
        "llm": {
            "call_count": llm_stats["count"],
            "avg_duration": llm_stats["avg"],
            "error_count": llm_errors,
            "tokens_generated": llm_tokens,
            "by_provider": llm_by_provider,
        },
        "rag": {
            "query_count": rag_stats["count"],
            "avg_duration": rag_stats["avg"],
            "by_status": rag_by_status,
        },
        "retrieval": {
            "search_count": retrieval_stats["count"],
            "avg_duration": retrieval_stats["avg"],
            "by_type": retrieval_by_type,
        },
        "embedding": {
            "call_count": embedding_stats["count"],
            "avg_duration": embedding_stats["avg"],
            "texts_processed": embedding_texts,
        },
        "ingestion": {
            "documents_total": sum(ingest_by_status.values()),
            "success_count": ingest_by_status.get("success", 0),
            "error_count": ingest_by_status.get("error", 0),
            "avg_duration": ingest_duration["avg"],
            "chunks_total": chunks_total,
            "queue_depth": queue_depth,
            "by_type": ingest_by_type,
        },
        "policy": {
            "total": sum(policy_by_result.values()),
            "blocked": policy_by_result.get("blocked", 0),
            "passed": policy_by_result.get("passed", 0),
            "by_result": policy_by_result,
        },
        "health": health,
    }


@router.get("/logs")
def get_logs(
    limit: int = Query(100, ge=1, le=500),
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    since_minutes: Optional[int] = Query(None, ge=1, le=1440),
    user: dict = Depends(get_current_user),
):
    """Query recent application logs from the in-memory buffer."""
    buf = get_log_buffer()
    since = time.time() - (since_minutes * 60) if since_minutes else None
    entries = buf.get_entries(limit=limit, level=level, search=search, since=since)
    counts = buf.count_by_level()
    return {
        "entries": entries,
        "counts": counts,
        "total_buffered": sum(counts.values()),
    }
