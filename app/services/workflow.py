"""LangGraph-based RAG workflow.

Defines a state-machine workflow with the following stages:
  1. **Rewrite** — optional query rewriting for better retrieval
  2. **Retrieve** — vector search for relevant document chunks
  3. **Judge** — ReAct relevance check; may loop back to retrieve with sub-questions
  4. **Draft** — LLM answer generation with output policy check
  5. **Approval** — optional human-in-the-loop approval
  6. **Final** — pass-through when no approval is required

The graph is compiled once at module level and reused for every request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.services.approvals import create_approval_request
from app.services.llm import generate_answer
from app.services.policy import evaluate_output_policy
from app.services.query_rewrite import rewrite_query
from app.services.relevance_judge import judge_relevance
from app.services.retrieval import search_chunks

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict, total=False):
    """Typed dictionary carrying data through the workflow graph."""

    question: str
    tenant_id: str
    user_id: str
    retrieved: List[Tuple[str, float, str, list, str]]
    draft_answer: str
    policy_blocked: bool
    policy_violations: List[str]
    approval_required: bool
    approval_id: str
    # ReAct / query rewrite fields
    rewritten_query: str
    retrieval_attempts: int
    sub_questions: List[str]
    all_contexts: List[Tuple[str, float, str, list, str]]
    # Source document IDs for approval policy
    source_document_ids: List[str]


def rewrite_node(state: WorkflowState) -> WorkflowState:
    """Rewrite the user question for better retrieval if enabled.

    Runs the async rewrite_query function synchronously via asyncio
    since LangGraph nodes in this workflow are synchronous.
    """
    question = state["question"]
    if not settings.query_rewrite_enabled:
        return {"rewritten_query": question}

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an already-running event loop (e.g. FastAPI).
            # Use a new thread to run the coroutine.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                rewritten = pool.submit(
                    lambda: asyncio.run(rewrite_query(question))
                ).result()
        else:
            rewritten = loop.run_until_complete(rewrite_query(question))
    except RuntimeError:
        rewritten = asyncio.run(rewrite_query(question))

    logger.info("Query rewritten: '%s' -> '%s'", question, rewritten)
    return {"rewritten_query": rewritten}


def retrieve_node(state: WorkflowState) -> WorkflowState:
    """Search Qdrant for the top-k chunks matching the query,
    scoped to the request's tenant.

    On the first attempt, uses the rewritten query.
    On subsequent attempts, searches for each sub-question and merges results.
    """
    attempts = state.get("retrieval_attempts", 0)
    all_contexts = list(state.get("all_contexts", []))
    sub_questions = state.get("sub_questions", [])
    tenant_id = state["tenant_id"]

    if attempts > 0 and sub_questions:
        # Retry: search with each sub-question
        new_matches = []
        seen_texts = {text for text, *_ in all_contexts}
        for sq in sub_questions:
            sq_matches = search_chunks(sq, settings.top_k, tenant_id)
            for match in sq_matches:
                if match[0] not in seen_texts:
                    new_matches.append(match)
                    seen_texts.add(match[0])
        all_contexts.extend(new_matches)
        matches = all_contexts
    else:
        # First attempt: use rewritten query
        query = state.get("rewritten_query", state["question"])
        matches = search_chunks(query, settings.top_k, tenant_id)
        all_contexts = list(matches)

    # Extract unique document IDs from retrieved chunks
    doc_ids = list({m[4] for m in matches if len(m) > 4 and m[4]})

    return {
        "retrieved": matches,
        "retrieval_attempts": attempts + 1,
        "all_contexts": all_contexts,
        "source_document_ids": doc_ids,
    }


def judge_node(state: WorkflowState) -> WorkflowState:
    """Judge whether retrieved contexts are sufficient to answer the question.

    Uses the async judge_relevance function. If ReAct is disabled or max
    attempts reached, skips judging and marks as sufficient.
    """
    attempts = state.get("retrieval_attempts", 1)

    if not settings.react_retrieval_enabled or attempts >= settings.max_retrieval_attempts:
        return {"sub_questions": []}

    contexts = [text for text, *_ in state.get("retrieved", [])]
    question = state["question"]

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    lambda: asyncio.run(judge_relevance(question, contexts))
                ).result()
        else:
            result = loop.run_until_complete(judge_relevance(question, contexts))
    except RuntimeError:
        result = asyncio.run(judge_relevance(question, contexts))

    logger.info(
        "Relevance judge (attempt %d): sufficient=%s, sub_questions=%s",
        attempts, result["is_sufficient"], result.get("sub_questions", []),
    )

    if result["is_sufficient"]:
        return {"sub_questions": []}
    return {"sub_questions": result.get("sub_questions", [])}


def draft_node(state: WorkflowState) -> WorkflowState:
    """Generate an LLM answer from retrieved contexts, then run the
    output policy evaluator to check for sensitive patterns."""
    retrieved = state.get("retrieved", [])
    contexts = [m[0] for m in retrieved]
    sources = [m[2] for m in retrieved]
    raw_answer = generate_answer(state["question"], contexts, sources)
    policy_result = evaluate_output_policy(raw_answer)
    return {
        "draft_answer": policy_result.answer,
        "policy_blocked": policy_result.blocked,
        "policy_violations": policy_result.matched_rules,
    }


def approval_node(state: WorkflowState) -> WorkflowState:
    """Create a pending approval request so a human reviewer can
    approve or reject the generated answer before it is released."""
    approval_id = create_approval_request(
        user_id=state["user_id"],
        tenant_id=state["tenant_id"],
        question=state["question"],
        draft_answer=state["draft_answer"],
    )
    return {"approval_required": True, "approval_id": approval_id}


def final_node(_: WorkflowState) -> WorkflowState:
    """Terminal node — marks the answer as not requiring approval."""
    return {"approval_required": False}


def route_after_judge(state: WorkflowState) -> str:
    """Conditional edge after judge: if sub-questions exist and haven't
    hit max attempts, go back to retrieve; otherwise proceed to draft."""
    sub_questions = state.get("sub_questions", [])
    attempts = state.get("retrieval_attempts", 1)
    if sub_questions and attempts < settings.max_retrieval_attempts:
        return "retrieve"
    return "draft"


def route_after_draft(state: WorkflowState) -> str:
    """Conditional edge: skip approval when the policy blocked the answer
    or when approval is not required per tenant/document policy."""
    if state.get("policy_blocked"):
        return "final"

    from app.services.approval_policy import should_require_approval
    doc_ids = state.get("source_document_ids", [])
    if should_require_approval(state["tenant_id"], doc_ids):
        return "approval"
    return "final"


# ── Build the LangGraph state graph ──────────────────────────────────────────
builder = StateGraph(WorkflowState)

# Register nodes
builder.add_node("rewrite", rewrite_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("judge", judge_node)
builder.add_node("draft", draft_node)
builder.add_node("approval", approval_node)
builder.add_node("final", final_node)

# Wire edges: START -> rewrite -> retrieve -> judge -> (conditional) -> draft -> (conditional) -> END
builder.add_edge(START, "rewrite")
builder.add_edge("rewrite", "retrieve")
builder.add_edge("retrieve", "judge")
builder.add_conditional_edges(
    "judge",
    route_after_judge,
    {"retrieve": "retrieve", "draft": "draft"},
)
builder.add_conditional_edges(
    "draft",
    route_after_draft,
    {"approval": "approval", "final": "final"},
)
builder.add_edge("approval", END)
builder.add_edge("final", END)

# Compile once — the compiled graph is thread-safe and reusable
workflow_graph = builder.compile()


def run_workflow(question: str, tenant_id: str, user_id: str) -> WorkflowState:
    """Execute the full RAG workflow and return the final state."""
    return workflow_graph.invoke(
        {"question": question, "tenant_id": tenant_id, "user_id": user_id}
    )
