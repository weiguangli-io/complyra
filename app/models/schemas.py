"""Pydantic request/response schemas for all API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Credentials for the login endpoint."""

    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    default_tenant_id: Optional[str] = None


class IngestSubmitResponse(BaseModel):
    job_id: str
    status: str


class IngestJobResponse(BaseModel):
    job_id: str
    tenant_id: str
    filename: str
    status: str
    chunks_indexed: int
    document_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)


class RetrievedChunk(BaseModel):
    text: str
    score: float
    source: Optional[str] = None
    page_numbers: List[int] = []


class ChatResponse(BaseModel):
    status: Literal["pending_approval", "completed"]
    answer: str
    retrieved: list[RetrievedChunk]
    approval_id: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    approved: bool
    note: Optional[str] = ""


class ApprovalResponse(BaseModel):
    approval_id: str
    user_id: str
    tenant_id: str
    status: str
    question: str
    draft_answer: str
    final_answer: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None
    decision_by: Optional[str] = None
    decision_note: Optional[str] = None


class AuditRecord(BaseModel):
    id: int
    timestamp: datetime
    tenant_id: str
    user: str
    action: str
    input_text: str
    output_text: str
    metadata: str


class TenantCreateRequest(BaseModel):
    tenant_id: Optional[str] = None
    name: str


class TenantResponse(BaseModel):
    tenant_id: str
    name: str
    created_at: datetime


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = Field(default="user", pattern="^(admin|user|auditor)$")
    default_tenant_id: Optional[str] = None


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str
    default_tenant_id: Optional[str] = None
    tenant_ids: list[str]
    created_at: datetime


class StreamEvent(BaseModel):
    """Schema for SSE stream events sent by ``POST /chat/stream``."""

    event: str
    data: dict


class AssignTenantRequest(BaseModel):
    tenant_id: str


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
