from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import get_tenant_id, require_roles
from app.core.config import settings
from app.models.schemas import (
    DocumentBulkRequest,
    DocumentBulkResponse,
    DocumentDetailResponse,
    DocumentInfo,
    DocumentListResponse,
    DocumentUpdateRequest,
)
from app.services.audit import log_event
from app.services.documents import (
    bulk_delete_documents,
    bulk_update_sensitivity,
    get_document_detail,
    get_preview_path,
    list_tenant_documents,
    update_document_fields,
)
from app.services.retrieval import delete_document, list_documents

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_to_response(doc) -> DocumentDetailResponse:
    return DocumentDetailResponse(
        document_id=doc.document_id,
        tenant_id=doc.tenant_id,
        filename=doc.filename,
        mime_type=doc.mime_type,
        file_size=doc.file_size,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        sensitivity=doc.sensitivity,
        status=doc.status,
        approval_override=doc.approval_override,
        created_by=doc.created_by,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("/", response_model=DocumentListResponse)
def get_documents(
    status: str = Query("active", pattern=r"^(active|archived|deleted|all)$"),
    sensitivity: str | None = Query(None, pattern=r"^(normal|sensitive|restricted)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin", "auditor"])),
) -> DocumentListResponse:
    """List documents with filtering and pagination."""
    effective_status = None if status == "all" else status
    docs, total = list_tenant_documents(
        tenant_id, status=effective_status, sensitivity=sensitivity, limit=limit, offset=offset,
    )
    return DocumentListResponse(items=[_doc_to_response(d) for d in docs], total=total)


@router.get("/legacy", response_model=list[DocumentInfo])
def get_documents_legacy(
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin", "auditor"])),
) -> list[DocumentInfo]:
    """Legacy endpoint: list documents from Qdrant (for backward compatibility)."""
    docs = list_documents(tenant_id)
    return [
        DocumentInfo(document_id=d["document_id"], filename=d["source"], chunk_count=d["chunk_count"])
        for d in docs
    ]


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin", "auditor"])),
) -> DocumentDetailResponse:
    """Get a single document's details."""
    doc = get_document_detail(document_id, tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_to_response(doc)


@router.patch("/{document_id}", response_model=DocumentDetailResponse)
def update_document(
    document_id: str,
    payload: DocumentUpdateRequest,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin"])),
) -> DocumentDetailResponse:
    """Update document sensitivity or approval override."""
    # Distinguish "field not sent" vs "field sent as null":
    # Pydantic sets fields not in the JSON body to their defaults;
    # model_fields_set tracks which fields were actually in the payload.
    if "approval_override" in payload.model_fields_set:
        override_val = payload.approval_override  # could be None (clear) or a string
    else:
        override_val = "__unset__"  # field not sent — don't change

    doc = update_document_fields(
        document_id,
        tenant_id,
        sensitivity=payload.sensitivity,
        approval_override=override_val,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    log_event(
        tenant_id=tenant_id,
        user=user["username"],
        action="document_updated",
        input_text=document_id,
        output_text=f"sensitivity={doc.sensitivity}, approval_override={doc.approval_override}",
        metadata="{}",
    )
    return _doc_to_response(doc)


@router.delete("/{document_id}")
def remove_document(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin"])),
) -> dict:
    """Soft-delete a document and remove its chunks from Qdrant."""
    doc = get_document_detail(document_id, tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Soft-delete in SQL
    from app.db.audit_db import update_document_db
    update_document_db(document_id=document_id, status="deleted")

    # Remove from Qdrant
    deleted = delete_document(document_id, tenant_id)

    log_event(
        tenant_id=tenant_id,
        user=user["username"],
        action="document_deleted",
        input_text=document_id,
        output_text=f"{deleted} chunks deleted",
        metadata="{}",
    )
    return {"document_id": document_id, "deleted_chunks": deleted}


@router.post("/bulk", response_model=DocumentBulkResponse)
def bulk_operation(
    payload: DocumentBulkRequest,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin"])),
) -> DocumentBulkResponse:
    """Bulk operations: delete or update sensitivity for multiple documents."""
    if payload.action == "delete":
        count = bulk_delete_documents(payload.document_ids, tenant_id)
    elif payload.action == "update_sensitivity":
        if not payload.sensitivity:
            raise HTTPException(status_code=400, detail="sensitivity is required for update_sensitivity action")
        count = bulk_update_sensitivity(payload.document_ids, tenant_id, payload.sensitivity)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {payload.action}")

    log_event(
        tenant_id=tenant_id,
        user=user["username"],
        action=f"document_bulk_{payload.action}",
        input_text=f"{len(payload.document_ids)} documents",
        output_text=f"{count} affected",
        metadata="{}",
    )
    return DocumentBulkResponse(affected=count)


@router.get("/{document_id}/preview")
def preview_document(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin", "auditor", "user"])),
):
    """Serve the original uploaded file for browser preview."""
    path = get_preview_path(document_id, tenant_id)
    if not path:
        raise HTTPException(status_code=404, detail="Preview not available")

    # Security: ensure path is within the configured preview storage
    preview_root = Path(settings.document_preview_storage_path).resolve()
    resolved_path = path.resolve()
    if not str(resolved_path).startswith(str(preview_root)):
        raise HTTPException(status_code=403, detail="Access denied")

    doc = get_document_detail(document_id, tenant_id)
    media_type = doc.mime_type if doc else "application/octet-stream"

    return FileResponse(
        path=str(resolved_path),
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename=\"{doc.filename if doc else 'file'}\""},
    )
