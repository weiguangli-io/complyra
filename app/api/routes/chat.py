"""Chat API endpoints.

Provides both synchronous (``POST /chat/``) and streaming
(``POST /chat/stream``) question-answering endpoints with
tenant-scoped retrieval, policy checks, and approval workflow.

The streaming endpoint supports query rewriting and ReAct multi-step
retrieval when enabled in settings.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user, get_tenant_id
from app.core.config import settings
from app.models.schemas import ChatRequest, ChatResponse, RetrievedChunk
from app.services.approvals import create_approval_request
from app.services.audit import log_event
from app.services.llm import generate_answer_stream
from app.services.policy import evaluate_output_policy
from app.services.query_rewrite import rewrite_query
from app.services.relevance_judge import judge_relevance
from app.services.retrieval import search_chunks
from app.services.workflow import run_workflow

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(get_current_user),
) -> ChatResponse:
    """Synchronous chat endpoint — returns a complete JSON response.

    Uses the LangGraph workflow which includes rewrite, retrieve,
    judge, and draft nodes.
    """
    state = run_workflow(payload.question, tenant_id, user["user_id"])
    matches = state.get("retrieved", [])
    approval_required = state.get("approval_required", False)
    approval_id = state.get("approval_id")
    policy_blocked = state.get("policy_blocked", False)
    policy_violations = state.get("policy_violations", [])

    retrieved = [
        RetrievedChunk(text=text, score=score, source=source, page_numbers=pages)
        for text, score, source, pages in matches
    ]

    if approval_required:
        answer = "Your request is pending human approval."
        status = "pending_approval"
    else:
        answer = state.get("draft_answer", "")
        status = "completed"

    if policy_blocked:
        action = "chat_blocked_by_policy"
    elif approval_required:
        action = "chat_pending"
    else:
        action = "chat_completed"

    log_event(
        tenant_id=tenant_id,
        user=user["username"],
        action=action,
        input_text=payload.question,
        output_text=answer,
        metadata=json.dumps(
            {
                "approval_id": approval_id or "",
                "policy_blocked": policy_blocked,
                "policy_violations": policy_violations,
            }
        ),
    )

    return ChatResponse(
        status=status, answer=answer, retrieved=retrieved, approval_id=approval_id
    )


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Events message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(get_current_user),
):
    """Streaming chat endpoint — returns Server-Sent Events with
    query rewriting, ReAct multi-step retrieval, token-by-token LLM
    output, policy check, and approval status.
    """

    async def event_generator():
        question = payload.question

        # Step 0: Query rewriting (if enabled)
        if settings.query_rewrite_enabled:
            yield _sse_event("rewrite_start", {})
            rewritten = await rewrite_query(question)
            yield _sse_event("rewrite_done", {
                "original_query": question,
                "rewritten_query": rewritten,
            })
            search_query = rewritten
        else:
            search_query = question

        # Step 1: Retrieve with ReAct loop (up to max_retrieval_attempts)
        all_matches = []
        seen_texts: set[str] = set()
        max_attempts = settings.max_retrieval_attempts if settings.react_retrieval_enabled else 1

        for attempt in range(1, max_attempts + 1):
            yield _sse_event("retrieve_start", {"attempt": attempt})

            if attempt == 1:
                # First attempt: use rewritten query
                new_matches = await asyncio.to_thread(
                    search_chunks, search_query, settings.top_k, tenant_id
                )
            else:
                # Subsequent attempts: search with sub-questions
                new_matches = []
                for sq in sub_questions:
                    sq_results = await asyncio.to_thread(
                        search_chunks, sq, settings.top_k, tenant_id
                    )
                    for match in sq_results:
                        if match[0] not in seen_texts:
                            new_matches.append(match)

            # Deduplicate and accumulate
            for match in new_matches:
                if match[0] not in seen_texts:
                    all_matches.append(match)
                    seen_texts.add(match[0])

            retrieved = [
                {"text": t, "score": s, "source": src, "page_numbers": pgs}
                for t, s, src, pgs in all_matches
            ]
            yield _sse_event("retrieve_done", {
                "attempt": attempt,
                "retrieved": retrieved,
            })

            # Judge relevance (if ReAct enabled and not last attempt)
            if settings.react_retrieval_enabled and attempt < max_attempts:
                yield _sse_event("judge_start", {"attempt": attempt})
                contexts = [t for t, *_ in all_matches]
                judge_result = await judge_relevance(question, contexts)
                is_sufficient = judge_result["is_sufficient"]
                sub_questions = judge_result.get("sub_questions", [])
                yield _sse_event("judge_done", {
                    "attempt": attempt,
                    "is_sufficient": is_sufficient,
                    "sub_questions": sub_questions,
                    "reasoning": judge_result.get("reasoning", ""),
                })

                if is_sufficient or not sub_questions:
                    break
            else:
                # Either ReAct is disabled or we've hit max attempts
                break

        matches = all_matches

        # Step 2: Stream LLM generation token by token
        yield _sse_event("generate_start", {})
        contexts = [t for t, *_ in matches]
        sources = [src for _, _, src, *_ in matches]
        full_answer: list[str] = []
        async for token in generate_answer_stream(question, contexts, sources):
            full_answer.append(token)
            yield _sse_event("token", {"text": token})

        # Step 3: Output policy check
        answer_text = "".join(full_answer)
        policy_result = await asyncio.to_thread(evaluate_output_policy, answer_text)
        if policy_result.blocked:
            yield _sse_event(
                "policy_blocked", {"violations": policy_result.matched_rules}
            )
            answer_text = settings.output_policy_block_message
        else:
            yield _sse_event("policy_passed", {})

        # Step 4: Approval workflow
        approval_id = None
        if not policy_result.blocked and settings.require_approval:
            approval_id = await asyncio.to_thread(
                create_approval_request,
                user_id=user["user_id"],
                tenant_id=tenant_id,
                question=question,
                draft_answer=answer_text,
            )
            yield _sse_event(
                "approval_required", {"approval_id": approval_id}
            )
        else:
            yield _sse_event("done", {"answer": answer_text})

        # Audit log
        if policy_result.blocked:
            action = "chat_stream_blocked_by_policy"
        elif approval_id:
            action = "chat_stream_pending"
        else:
            action = "chat_stream_completed"

        log_event(
            tenant_id=tenant_id,
            user=user["username"],
            action=action,
            input_text=question,
            output_text=answer_text,
            metadata=json.dumps(
                {
                    "approval_id": approval_id or "",
                    "policy_blocked": policy_result.blocked,
                    "policy_violations": policy_result.matched_rules,
                    "streaming": True,
                }
            ),
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")
