"""Document lifecycle management service."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

from app.db.audit_db import (
    create_document_record as _create_doc,
    get_document,
    list_documents_db,
    update_document_db,
    bulk_update_documents_db,
    get_documents_by_ids,
)
from app.db.models import Document
from app.services.retrieval import delete_document as delete_qdrant_doc


def detect_mime_type(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def create_document(
    *,
    document_id: str,
    tenant_id: str,
    filename: str,
    file_size: int,
    page_count: int,
    chunk_count: int,
    created_by: str,
    storage_path: Optional[str] = None,
) -> Document:
    return _create_doc(
        document_id=document_id,
        tenant_id=tenant_id,
        filename=filename,
        mime_type=detect_mime_type(filename),
        file_size=file_size,
        page_count=page_count,
        chunk_count=chunk_count,
        created_by=created_by,
        storage_path=storage_path,
    )


def get_document_detail(document_id: str, tenant_id: str) -> Optional[Document]:
    doc = get_document(document_id)
    if doc and doc.tenant_id == tenant_id:
        return doc
    return None


def list_tenant_documents(
    tenant_id: str,
    *,
    status: Optional[str] = "active",
    sensitivity: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Document], int]:
    return list_documents_db(
        tenant_id=tenant_id,
        status=status,
        sensitivity=sensitivity,
        limit=limit,
        offset=offset,
    )


def update_sensitivity(document_id: str, tenant_id: str, sensitivity: str) -> Optional[Document]:
    doc = get_document(document_id)
    if not doc or doc.tenant_id != tenant_id:
        return None
    return update_document_db(document_id=document_id, sensitivity=sensitivity)


def update_approval_override(document_id: str, tenant_id: str, override: Optional[str]) -> Optional[Document]:
    doc = get_document(document_id)
    if not doc or doc.tenant_id != tenant_id:
        return None
    return update_document_db(document_id=document_id, approval_override=override)


def update_document_fields(
    document_id: str,
    tenant_id: str,
    *,
    sensitivity: Optional[str] = None,
    approval_override: str = "__unset__",
) -> Optional[Document]:
    doc = get_document(document_id)
    if not doc or doc.tenant_id != tenant_id:
        return None
    return update_document_db(
        document_id=document_id,
        sensitivity=sensitivity,
        approval_override=approval_override if approval_override != "__unset__" else "__unset__",
    )


def bulk_update_sensitivity(document_ids: list[str], tenant_id: str, sensitivity: str) -> int:
    return bulk_update_documents_db(
        document_ids=document_ids,
        tenant_id=tenant_id,
        sensitivity=sensitivity,
    )


def bulk_delete_documents(document_ids: list[str], tenant_id: str) -> int:
    count = bulk_update_documents_db(
        document_ids=document_ids,
        tenant_id=tenant_id,
        status="deleted",
    )
    for doc_id in document_ids:
        delete_qdrant_doc(doc_id, tenant_id)
    return count


def get_preview_path(document_id: str, tenant_id: str) -> Optional[Path]:
    doc = get_document_detail(document_id, tenant_id)
    if not doc or not doc.storage_path:
        return None
    path = Path(doc.storage_path)
    if not path.exists():
        return None
    return path
