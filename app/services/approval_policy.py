"""Per-tenant, per-document approval policy resolution."""

from __future__ import annotations

from app.core.config import settings
from app.db.audit_db import get_documents_by_ids, get_tenant_policy, upsert_tenant_policy
from app.db.models import TenantPolicy


def get_tenant_approval_mode(tenant_id: str) -> str:
    policy = get_tenant_policy(tenant_id)
    if policy:
        return policy.approval_mode
    return "all" if settings.require_approval else "none"


def set_tenant_approval_mode(tenant_id: str, mode: str, updated_by: str) -> TenantPolicy:
    return upsert_tenant_policy(tenant_id=tenant_id, approval_mode=mode, updated_by=updated_by)


def should_require_approval(tenant_id: str, document_ids: list[str]) -> bool:
    """Determine if approval is needed based on:
    1. Per-document approval_override ('always'/'never') takes precedence
    2. Tenant policy ('all'/'sensitive'/'none')
    3. Fallback to global settings.require_approval
    """
    docs = get_documents_by_ids(document_ids)

    # Check per-document overrides first
    has_always = False
    policy_docs = []
    for doc in docs:
        if doc.approval_override == "always":
            has_always = True
        elif doc.approval_override == "never":
            continue  # skip this doc
        else:
            policy_docs.append(doc)

    if has_always:
        return True

    # Get tenant-level policy
    mode = get_tenant_approval_mode(tenant_id)

    if mode == "all":
        return True
    if mode == "none":
        return False
    # mode == "sensitive"
    return any(doc.sensitivity in ("sensitive", "restricted") for doc in policy_docs)
