from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_roles
from app.models.schemas import TenantCreateRequest, TenantPolicyResponse, TenantPolicyUpdateRequest, TenantResponse
from app.services.approval_policy import get_tenant_approval_mode, set_tenant_approval_mode
from app.services.audit import log_event
from app.services.users import create_tenant_account, get_tenant_account, list_tenant_accounts

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("/", response_model=TenantResponse)
def create_tenant(payload: TenantCreateRequest, user: dict = Depends(require_roles(["admin"]))):
    tenant_id = payload.tenant_id or payload.name.lower().replace(" ", "-")
    try:
        row = create_tenant_account(tenant_id, payload.name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Tenant creation failed") from exc

    if not row:
        row = get_tenant_account(tenant_id)
    if not row:
        raise HTTPException(status_code=500, detail="Tenant created but not found")

    log_event(
        tenant_id=user.get("default_tenant_id") or tenant_id,
        user=user["username"],
        action="tenant_create",
        input_text=tenant_id,
        output_text=row.name,
        metadata="{}",
    )

    return TenantResponse(tenant_id=row.tenant_id, name=row.name, created_at=row.created_at)


@router.get("/", response_model=list[TenantResponse])
def list_tenants(_current_user: dict = Depends(require_roles(["admin"]))):
    rows = list_tenant_accounts()
    return [TenantResponse(tenant_id=row.tenant_id, name=row.name, created_at=row.created_at) for row in rows]


@router.get("/{tenant_id}/policy", response_model=TenantPolicyResponse)
def get_policy(
    tenant_id: str,
    _current_user: dict = Depends(require_roles(["admin"])),
) -> TenantPolicyResponse:
    from app.db.audit_db import get_tenant_policy
    policy = get_tenant_policy(tenant_id)
    if policy:
        return TenantPolicyResponse(
            tenant_id=policy.tenant_id,
            approval_mode=policy.approval_mode,
            updated_at=policy.updated_at,
            updated_by=policy.updated_by,
        )
    return TenantPolicyResponse(
        tenant_id=tenant_id,
        approval_mode=get_tenant_approval_mode(tenant_id),
    )


@router.put("/{tenant_id}/policy", response_model=TenantPolicyResponse)
def update_policy(
    tenant_id: str,
    payload: TenantPolicyUpdateRequest,
    current_user: dict = Depends(require_roles(["admin"])),
) -> TenantPolicyResponse:
    policy = set_tenant_approval_mode(tenant_id, payload.approval_mode, current_user["username"])
    log_event(
        tenant_id=tenant_id,
        user=current_user["username"],
        action="policy_updated",
        input_text=f"approval_mode={payload.approval_mode}",
        output_text="",
        metadata="{}",
    )
    return TenantPolicyResponse(
        tenant_id=policy.tenant_id,
        approval_mode=policy.approval_mode,
        updated_at=policy.updated_at,
        updated_by=policy.updated_by,
    )
