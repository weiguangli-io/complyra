"""Tests for the relevance judge service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.relevance_judge import (
    _format_contexts,
    _parse_judge_response,
    judge_relevance,
)


class TestFormatContexts:
    def test_formats_numbered_contexts(self):
        result = _format_contexts(["ctx1", "ctx2"])
        assert "[1] ctx1" in result
        assert "[2] ctx2" in result

    def test_empty_contexts(self):
        result = _format_contexts([])
        assert "no contexts" in result.lower()


class TestParseJudgeResponse:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "All info present",
        })
        result = _parse_judge_response(raw)
        assert result["is_sufficient"] is True
        assert result["sub_questions"] == []
        assert result["reasoning"] == "All info present"

    def test_parses_insufficient_with_sub_questions(self):
        raw = json.dumps({
            "is_sufficient": False,
            "sub_questions": ["What is X?", "How does Y work?"],
            "reasoning": "Missing details",
        })
        result = _parse_judge_response(raw)
        assert result["is_sufficient"] is False
        assert len(result["sub_questions"]) == 2

    def test_strips_markdown_fences(self):
        raw = '```json\n{"is_sufficient": true, "sub_questions": [], "reasoning": "ok"}\n```'
        result = _parse_judge_response(raw)
        assert result["is_sufficient"] is True

    def test_handles_invalid_json_gracefully(self):
        result = _parse_judge_response("not valid json at all")
        assert result["is_sufficient"] is True
        assert result["sub_questions"] == []
        assert "failed" in result["reasoning"].lower() or "Failed" in result["reasoning"]


class TestJudgeRelevance:
    @pytest.mark.asyncio
    @patch("app.services.relevance_judge._judge_gemini", new_callable=AsyncMock)
    async def test_returns_sufficient_when_contexts_good(self, mock_gemini, monkeypatch):
        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.services.relevance_judge.settings.llm_provider", "gemini")
        mock_gemini.return_value = {
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "Contexts cover the question fully.",
        }

        result = await judge_relevance("What is X?", ["X is a thing."])
        assert result["is_sufficient"] is True
        assert result["sub_questions"] == []

    @pytest.mark.asyncio
    @patch("app.services.relevance_judge._judge_gemini", new_callable=AsyncMock)
    async def test_returns_insufficient_with_sub_questions(self, mock_gemini, monkeypatch):
        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.services.relevance_judge.settings.llm_provider", "gemini")
        mock_gemini.return_value = {
            "is_sufficient": False,
            "sub_questions": ["What is the deadline?", "Who is responsible?"],
            "reasoning": "Missing key details.",
        }

        result = await judge_relevance("Tell me about the project", ["Some vague info"])
        assert result["is_sufficient"] is False
        assert len(result["sub_questions"]) == 2

    @pytest.mark.asyncio
    async def test_returns_sufficient_when_react_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", False)

        result = await judge_relevance("Any question", ["any context"])
        assert result["is_sufficient"] is True
        assert result["sub_questions"] == []
        assert "disabled" in result["reasoning"].lower()

    @pytest.mark.asyncio
    @patch("app.services.relevance_judge._judge_gemini", new_callable=AsyncMock)
    async def test_handles_exception_gracefully(self, mock_gemini, monkeypatch):
        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.services.relevance_judge.settings.llm_provider", "gemini")
        mock_gemini.side_effect = Exception("Network error")

        result = await judge_relevance("question", ["context"])
        assert result["is_sufficient"] is True
        assert result["sub_questions"] == []
        assert "failed" in result["reasoning"].lower()

    @pytest.mark.asyncio
    @patch("app.services.relevance_judge._judge_ollama", new_callable=AsyncMock)
    async def test_uses_ollama_provider(self, mock_ollama, monkeypatch):
        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.services.relevance_judge.settings.llm_provider", "ollama")
        mock_ollama.return_value = {
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "Good enough.",
        }

        result = await judge_relevance("q", ["c"])
        assert result["is_sufficient"] is True
        mock_ollama.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.relevance_judge._judge_openai", new_callable=AsyncMock)
    async def test_uses_openai_provider(self, mock_openai, monkeypatch):
        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.services.relevance_judge.settings.llm_provider", "openai")
        mock_openai.return_value = {
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "OpenAI judge.",
        }

        result = await judge_relevance("q", ["c"])
        assert result["is_sufficient"] is True
        mock_openai.assert_awaited_once()


class TestJudgeGeminiInternal:
    @pytest.mark.asyncio
    async def test_judge_gemini(self, monkeypatch):
        from app.services.relevance_judge import _judge_gemini

        monkeypatch.setattr("app.services.relevance_judge.settings.gemini_chat_model", "gemini-2.5-flash")
        monkeypatch.setattr("app.services.relevance_judge.settings.gemini_api_key", "gem-key")

        judge_json = json.dumps({
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "All good",
        })
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": judge_json}]}}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.relevance_judge.httpx.AsyncClient", return_value=mock_client):
            result = await _judge_gemini("question", ["context"])
            assert result["is_sufficient"] is True


class TestJudgeOpenAIInternal:
    @pytest.mark.asyncio
    async def test_judge_openai(self, monkeypatch):
        from app.services.relevance_judge import _judge_openai

        monkeypatch.setattr("app.services.relevance_judge.settings.openai_api_key", "sk-test")
        monkeypatch.setattr("app.services.relevance_judge.settings.openai_chat_model", "gpt-4o-mini")

        judge_json = json.dumps({
            "is_sufficient": False,
            "sub_questions": ["sub1", "sub2"],
            "reasoning": "Missing info",
        })
        mock_msg = MagicMock()
        mock_msg.content = judge_json
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock(choices=[mock_choice])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        import sys
        mock_openai_mod = MagicMock()
        mock_openai_mod.AsyncOpenAI.return_value = mock_client
        with patch.dict(sys.modules, {"openai": mock_openai_mod}):
            result = await _judge_openai("question", ["context"])
            assert result["is_sufficient"] is False
            assert len(result["sub_questions"]) == 2


class TestJudgeOllamaInternal:
    @pytest.mark.asyncio
    async def test_judge_ollama(self, monkeypatch):
        from app.services.relevance_judge import _judge_ollama

        monkeypatch.setattr("app.services.relevance_judge.settings.ollama_model", "qwen2.5:3b-instruct")
        monkeypatch.setattr("app.services.relevance_judge.settings.ollama_base_url", "http://localhost:11434")
        monkeypatch.setattr("app.services.relevance_judge.settings.ollama_timeout_seconds", 60)

        judge_json = json.dumps({
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "OK",
        })
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": judge_json}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.relevance_judge.httpx.AsyncClient", return_value=mock_client):
            result = await _judge_ollama("question", ["context"])
            assert result["is_sufficient"] is True
