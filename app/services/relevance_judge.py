"""Judge retrieval relevance and decompose complex questions.

Uses the configured LLM provider to evaluate whether retrieved contexts
are sufficient to answer a given question. When contexts are insufficient,
generates sub-questions to guide additional retrieval rounds (ReAct pattern).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from langsmith import traceable

from app.core.config import settings

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = (
    "You are a relevance judge. Given a question and a list of retrieved contexts, "
    "determine whether the contexts contain enough information to fully answer the question.\n\n"
    "Question: {question}\n\n"
    "Retrieved contexts:\n{contexts}\n\n"
    "Respond with a JSON object (no markdown fences) with these fields:\n"
    '- "is_sufficient": true if the contexts contain enough information, false otherwise\n'
    '- "sub_questions": if not sufficient, a list of 2-3 specific sub-questions to search for '
    "to fill the information gaps. If sufficient, an empty list.\n"
    '- "reasoning": a brief explanation of your judgment\n\n'
    "JSON response:"
)


def _format_contexts(contexts: list[str]) -> str:
    """Format context list into numbered block for prompt."""
    if not contexts:
        return "(no contexts retrieved)"
    return "\n\n".join(f"[{i + 1}] {text}" for i, text in enumerate(contexts))


def _parse_judge_response(raw: str) -> dict[str, Any]:
    """Parse LLM response into structured dict, with fallback defaults."""
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        result = json.loads(text)
        return {
            "is_sufficient": bool(result.get("is_sufficient", True)),
            "sub_questions": list(result.get("sub_questions", [])),
            "reasoning": str(result.get("reasoning", "")),
        }
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse judge response, treating as sufficient: %s", text[:200])
        return {
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "Failed to parse LLM judge response; defaulting to sufficient.",
        }


# ── Gemini ─────────────────────────────────────────────────────

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


async def _judge_gemini(question: str, contexts: list[str]) -> dict[str, Any]:
    prompt = _JUDGE_PROMPT.format(question=question, contexts=_format_contexts(contexts))
    url = f"{_GEMINI_API_BASE}/{settings.gemini_chat_model}:generateContent?key={settings.gemini_api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_judge_response(raw)


# ── OpenAI ─────────────────────────────────────────────────────


async def _judge_openai(question: str, contexts: list[str]) -> dict[str, Any]:
    from openai import AsyncOpenAI

    prompt = _JUDGE_PROMPT.format(question=question, contexts=_format_contexts(contexts))
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    raw = response.choices[0].message.content
    return _parse_judge_response(raw)


# ── Ollama ─────────────────────────────────────────────────────


async def _judge_ollama(question: str, contexts: list[str]) -> dict[str, Any]:
    prompt = _JUDGE_PROMPT.format(question=question, contexts=_format_contexts(contexts))
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
        raw = data.get("response", "")
        return _parse_judge_response(raw)


# ── Public API ─────────────────────────────────────────────────


@traceable(name="judge_relevance", run_type="llm")
async def judge_relevance(question: str, contexts: list[str]) -> dict[str, Any]:
    """Use LLM to judge if retrieved contexts are sufficient to answer the question.

    Returns:
        {
            "is_sufficient": bool,
            "sub_questions": list[str],  # if not sufficient, decomposed sub-questions
            "reasoning": str
        }
    """
    if not settings.react_retrieval_enabled:
        return {
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "ReAct retrieval is disabled.",
        }

    try:
        if settings.llm_provider == "gemini":
            return await _judge_gemini(question, contexts)
        if settings.llm_provider == "openai":
            return await _judge_openai(question, contexts)
        return await _judge_ollama(question, contexts)
    except Exception:
        logger.warning("Relevance judging failed, treating as sufficient", exc_info=True)
        return {
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "Relevance judging failed; defaulting to sufficient.",
        }
