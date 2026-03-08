"""Query rewriting for improved retrieval accuracy.

Uses the configured LLM provider to transform user queries into
more effective search queries for the retrieval pipeline.
"""

from __future__ import annotations

import logging

import httpx
from langsmith import traceable

from app.core.config import settings

logger = logging.getLogger(__name__)

_REWRITE_PROMPT = (
    "You are a query rewriting assistant. Your task is to rewrite the user's "
    "query into a better search query for retrieving relevant documents.\n\n"
    "Rules:\n"
    "1. Extract the core information need from the query\n"
    "2. Add relevant technical or domain-specific terms\n"
    "3. Keep the language the same as the input (e.g. Chinese input -> Chinese output)\n"
    "4. Return ONLY the rewritten query, nothing else — no explanation, no quotes\n\n"
    "Original query: {query}\n"
    "Rewritten query:"
)

# ── Gemini ─────────────────────────────────────────────────────

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


async def _rewrite_gemini(query: str) -> str:
    prompt = _REWRITE_PROMPT.format(query=query)
    url = f"{_GEMINI_API_BASE}/{settings.gemini_chat_model}:generateContent?key={settings.gemini_api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


# ── OpenAI ─────────────────────────────────────────────────────


async def _rewrite_openai(query: str) -> str:
    from openai import AsyncOpenAI

    prompt = _REWRITE_PROMPT.format(query=query)
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()


# ── Ollama ─────────────────────────────────────────────────────


async def _rewrite_ollama(query: str) -> str:
    prompt = _REWRITE_PROMPT.format(query=query)
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/generate", json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()


# ── Public API ─────────────────────────────────────────────────


@traceable(name="rewrite_query", run_type="llm")
async def rewrite_query(original_query: str) -> str:
    """Use LLM to rewrite a user query into a better search query.

    Handles:
    - Colloquial/vague queries -> precise search terms
    - Chinese queries with mixed terminology
    - Multi-intent queries -> focused single query

    Returns original query if rewriting is disabled or fails.
    """
    if not settings.query_rewrite_enabled:
        return original_query

    try:
        if settings.llm_provider == "gemini":
            return await _rewrite_gemini(original_query)
        if settings.llm_provider == "openai":
            return await _rewrite_openai(original_query)
        return await _rewrite_ollama(original_query)
    except Exception:
        logger.warning("Query rewrite failed, using original query", exc_info=True)
        return original_query
