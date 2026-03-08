"""Tests for the query rewrite service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.query_rewrite import rewrite_query


class TestRewriteQuery:
    @pytest.mark.asyncio
    @patch("app.services.query_rewrite._rewrite_gemini", new_callable=AsyncMock)
    async def test_returns_rewritten_text_when_enabled(self, mock_gemini, monkeypatch):
        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", True)
        monkeypatch.setattr("app.services.query_rewrite.settings.llm_provider", "gemini")
        mock_gemini.return_value = "improved search query"

        result = await rewrite_query("vague question")
        assert result == "improved search query"
        mock_gemini.assert_awaited_once_with("vague question")

    @pytest.mark.asyncio
    async def test_returns_original_when_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", False)

        result = await rewrite_query("original question")
        assert result == "original question"

    @pytest.mark.asyncio
    @patch("app.services.query_rewrite._rewrite_gemini", new_callable=AsyncMock)
    async def test_returns_original_on_exception(self, mock_gemini, monkeypatch):
        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", True)
        monkeypatch.setattr("app.services.query_rewrite.settings.llm_provider", "gemini")
        mock_gemini.side_effect = Exception("API error")

        result = await rewrite_query("original question")
        assert result == "original question"

    @pytest.mark.asyncio
    @patch("app.services.query_rewrite._rewrite_ollama", new_callable=AsyncMock)
    async def test_uses_ollama_provider(self, mock_ollama, monkeypatch):
        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", True)
        monkeypatch.setattr("app.services.query_rewrite.settings.llm_provider", "ollama")
        mock_ollama.return_value = "ollama rewritten"

        result = await rewrite_query("test query")
        assert result == "ollama rewritten"
        mock_ollama.assert_awaited_once_with("test query")

    @pytest.mark.asyncio
    @patch("app.services.query_rewrite._rewrite_openai", new_callable=AsyncMock)
    async def test_uses_openai_provider(self, mock_openai, monkeypatch):
        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", True)
        monkeypatch.setattr("app.services.query_rewrite.settings.llm_provider", "openai")
        mock_openai.return_value = "openai rewritten"

        result = await rewrite_query("test query")
        assert result == "openai rewritten"
        mock_openai.assert_awaited_once_with("test query")


class TestRewriteGeminiInternal:
    @pytest.mark.asyncio
    async def test_rewrite_gemini(self, monkeypatch):
        from app.services.query_rewrite import _rewrite_gemini

        monkeypatch.setattr("app.services.query_rewrite.settings.gemini_chat_model", "gemini-2.5-flash")
        monkeypatch.setattr("app.services.query_rewrite.settings.gemini_api_key", "gem-key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "  rewritten query  "}]}}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.query_rewrite.httpx.AsyncClient", return_value=mock_client):
            result = await _rewrite_gemini("test query")
            assert result == "rewritten query"


class TestRewriteOpenAIInternal:
    @pytest.mark.asyncio
    async def test_rewrite_openai(self, monkeypatch):
        from app.services.query_rewrite import _rewrite_openai

        monkeypatch.setattr("app.services.query_rewrite.settings.openai_api_key", "sk-test")
        monkeypatch.setattr("app.services.query_rewrite.settings.openai_chat_model", "gpt-4o-mini")

        mock_msg = MagicMock()
        mock_msg.content = "  openai rewritten  "
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock(choices=[mock_choice])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.query_rewrite.AsyncOpenAI", mock_client, create=True):
            # AsyncOpenAI is imported locally, so we patch it in the openai module
            import sys
            mock_openai_mod = MagicMock()
            mock_openai_mod.AsyncOpenAI.return_value = mock_client
            with patch.dict(sys.modules, {"openai": mock_openai_mod}):
                result = await _rewrite_openai("test query")
                assert result == "openai rewritten"


class TestRewriteOllamaInternal:
    @pytest.mark.asyncio
    async def test_rewrite_ollama(self, monkeypatch):
        from app.services.query_rewrite import _rewrite_ollama

        monkeypatch.setattr("app.services.query_rewrite.settings.ollama_model", "qwen2.5:3b-instruct")
        monkeypatch.setattr("app.services.query_rewrite.settings.ollama_base_url", "http://localhost:11434")
        monkeypatch.setattr("app.services.query_rewrite.settings.ollama_timeout_seconds", 60)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "  ollama rewritten  "}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.query_rewrite.httpx.AsyncClient", return_value=mock_client):
            result = await _rewrite_ollama("test query")
            assert result == "ollama rewritten"
