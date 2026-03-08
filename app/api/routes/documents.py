from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_tenant_id, require_roles
from app.models.schemas import DocumentInfo
from app.services.audit import log_event
from app.services.retrieval import delete_document, list_documents

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/", response_model=list[DocumentInfo])
def get_documents(
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin", "auditor"])),
) -> list[DocumentInfo]:
    """List all documents for the current tenant."""
    docs = list_documents(tenant_id)
    return [
        DocumentInfo(
            document_id=d["document_id"],
            filename=d["source"],
            chunk_count=d["chunk_count"],
        )
        for d in docs
    ]


@router.delete("/{document_id}")
def remove_document(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(require_roles(["admin"])),
) -> dict:
    """Delete a document and all its chunks. Requires admin role."""
    deleted = delete_document(document_id, tenant_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document not found")

    log_event(
        tenant_id=tenant_id,
        user=user["username"],
        action="document_deleted",
        input_text=document_id,
        output_text=f"{deleted} chunks deleted",
        metadata="{}",
    )

    return {"document_id": document_id, "deleted_chunks": deleted}
