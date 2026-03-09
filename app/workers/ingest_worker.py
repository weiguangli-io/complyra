from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.core.config import settings
from app.db.audit_db import get_ingest_job, update_ingest_job
from app.services.ingest import ingest_document_from_path

logger = logging.getLogger(__name__)


def _count_pages(file_path: str, extension: str) -> int:
    """Count pages for PDF files."""
    if extension != "pdf":
        return 0
    try:
        import fitz
        doc = fitz.open(file_path)
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


def _move_to_preview_storage(file_path: str, document_id: str, filename: str) -> str | None:
    """Move the uploaded file to permanent preview storage. Returns the new path."""
    try:
        preview_dir = Path(settings.document_preview_storage_path)
        preview_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(filename).suffix
        dest = preview_dir / f"{document_id}{ext}"
        shutil.copy2(file_path, str(dest))
        return str(dest)
    except Exception:
        logger.warning("Failed to copy file to preview storage: %s", file_path, exc_info=True)
        return None


def process_ingest_job(job_id: str, file_path: str, filename: str, tenant_id: str) -> dict:
    update_ingest_job(job_id=job_id, status="processing")
    try:
        document_id, chunks_indexed = ingest_document_from_path(file_path, filename, tenant_id)
        if not document_id:
            update_ingest_job(job_id=job_id, status="failed", error_message="No text extracted from file")
            return {"status": "failed", "job_id": job_id}

        # Determine page count and move file for preview
        extension = Path(filename).suffix.lstrip(".").lower()
        page_count = _count_pages(file_path, extension)
        file_size = Path(file_path).stat().st_size if Path(file_path).exists() else 0
        preview_path = _move_to_preview_storage(file_path, document_id, filename)

        # Create SQL Document record
        job = get_ingest_job(job_id)
        created_by = job.created_by if job else "unknown"

        from app.services.documents import create_document
        create_document(
            document_id=document_id,
            tenant_id=tenant_id,
            filename=filename,
            file_size=file_size,
            page_count=page_count,
            chunk_count=chunks_indexed,
            created_by=created_by,
            storage_path=preview_path,
        )

        update_ingest_job(
            job_id=job_id,
            status="completed",
            chunks_indexed=chunks_indexed,
            document_id=document_id,
        )
        return {
            "status": "completed",
            "job_id": job_id,
            "document_id": document_id,
            "chunks_indexed": chunks_indexed,
        }
    except Exception as exc:  # pragma: no cover - job system catches broad exceptions
        update_ingest_job(job_id=job_id, status="failed", error_message=str(exc))
        return {"status": "failed", "job_id": job_id, "error": str(exc)}
    finally:
        path = Path(file_path)
        if path.exists():
            path.unlink(missing_ok=True)
