"""Tests for the LLM service (Ollama integration)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.llm import (
    _build_prompt,
    _generate_gemini,
    _generate_openai,
    _openai_client,
    describe_image,
    ensure_model_ready,
    generate_answer,
    generate_answer_stream,
    ollama_health,
)


class TestBuildPrompt:
    def test_includes_context_and_question(self):
        prompt = _build_prompt("What is X?", ["Context A", "Context B"])
        assert "Context A" in prompt
        assert "Context B" in prompt
        assert "What is X?" in prompt
        assert "Answer:" in prompt

    def test_includes_security_guardrail(self):
        prompt = _build_prompt("q", ["c"])
        assert "untrusted data" in prompt

    def test_empty_contexts(self):
        prompt = _build_prompt("q", [])
        assert "Question: q" in prompt

    def test_with_sources(self):
        prompt = _build_prompt("q", ["ctx1", "ctx2"], sources=["file1.pdf", "file2.pdf"])
        assert "(Source: file1.pdf)" in prompt
        assert "(Source: file2.pdf)" in prompt

    def test_with_mismatched_sources_falls_back(self):
        # sources length != contexts length -> no source annotation
        prompt = _build_prompt("q", ["ctx1", "ctx2"], sources=["only_one.pdf"])
        assert "(Source:" not in prompt


@pytest.fixture(autouse=True)
def _force_ollama_provider(monkeypatch):
    """Tests in this module target the Ollama code path."""
    monkeypatch.setattr("app.services.llm.settings.llm_provider", "ollama")


class TestGenerateAnswer:
    @patch("app.services.llm.httpx.Client")
    def test_returns_stripped_response(self, MockClient):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "  answer text  "}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        MockClient.return_value = mock_client

        result = generate_answer("question", ["context"])
        assert result == "answer text"

    @patch("app.services.llm.httpx.Client")
    def test_sends_correct_payload(self, MockClient):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "ok"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        MockClient.return_value = mock_client

        generate_answer("q", ["c"])
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["stream"] is False
        assert "prompt" in payload

    @patch("app.services.llm.httpx.Client")
    def test_empty_response(self, MockClient):
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        MockClient.return_value = mock_client

        result = generate_answer("q", ["c"])
        assert result == ""


class _AsyncLineIterator:
    """Helper to create a proper async iterator for mocking aiter_lines."""

    def __init__(self, lines):
        self._lines = lines
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._index]
        self._index += 1
        return line


class TestGenerateAnswerStream:
    @pytest.mark.asyncio
    async def test_yields_tokens(self):
        lines = [
            json.dumps({"response": "Hello", "done": False}),
            json.dumps({"response": " world", "done": True}),
        ]

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=_AsyncLineIterator(lines))
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            tokens = []
            async for token in generate_answer_stream("q", ["c"]):
                tokens.append(token)
            assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_skips_empty_tokens(self):
        lines = [
            json.dumps({"response": "", "done": False}),
            json.dumps({"response": "ok", "done": True}),
        ]

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=_AsyncLineIterator(lines))
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            tokens = []
            async for token in generate_answer_stream("q", ["c"]):
                tokens.append(token)
            assert tokens == ["ok"]


class TestOllamaHealth:
    @patch("app.services.llm.httpx.Client")
    def test_healthy(self, MockClient):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        MockClient.return_value = mock_client

        assert ollama_health() is True

    @patch("app.services.llm.httpx.Client")
    def test_unhealthy(self, MockClient):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("connection refused")
        MockClient.return_value = mock_client

        assert ollama_health() is False


class TestEnsureModelReady:
    @patch("app.services.llm.httpx.Client")
    def test_prepull_success(self, MockClient, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.ollama_prepull", True)
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        MockClient.return_value = mock_client

        assert ensure_model_ready() is True

    @patch("app.services.llm.httpx.Client")
    def test_prepull_failure(self, MockClient, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.ollama_prepull", True)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("timeout")
        MockClient.return_value = mock_client

        assert ensure_model_ready() is False

    def test_prepull_disabled(self, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.ollama_prepull", False)
        assert ensure_model_ready() is True


# ── OpenAI provider tests ──────────────────────────────────────


class TestOpenAIClient:
    def test_creates_openai_client(self, monkeypatch):
        mock_openai_class = MagicMock()
        import sys
        with patch.dict(sys.modules, {"openai": MagicMock(OpenAI=mock_openai_class)}):
            monkeypatch.setattr("app.services.llm.settings.openai_api_key", "sk-test")
            client = _openai_client()
            mock_openai_class.assert_called_once_with(api_key="sk-test")


class TestGenerateOpenAI:
    @patch("app.services.llm._openai_client")
    def test_returns_response(self, mock_client_fn, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "openai")
        monkeypatch.setattr("app.services.llm.settings.openai_chat_model", "gpt-4o-mini")
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "  openai answer  "
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        mock_client_fn.return_value = mock_client

        result = _generate_openai("question", ["context"])
        assert result == "openai answer"

    @patch("app.services.llm._openai_client")
    def test_generate_answer_openai_dispatch(self, mock_client_fn, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "openai")
        monkeypatch.setattr("app.services.llm.settings.openai_chat_model", "gpt-4o-mini")
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "answer"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        mock_client_fn.return_value = mock_client

        result = generate_answer("q", ["c"])
        assert result == "answer"


class TestGenerateOpenAIStream:
    @pytest.mark.asyncio
    @patch("app.services.llm._openai_client")
    async def test_yields_tokens(self, mock_client_fn, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "openai")
        monkeypatch.setattr("app.services.llm.settings.openai_chat_model", "gpt-4o-mini")

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="Hello"))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content=" world"))]
        chunk3 = MagicMock()
        chunk3.choices = [MagicMock(delta=MagicMock(content=None))]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = [chunk1, chunk2, chunk3]
        mock_client_fn.return_value = mock_client

        tokens = []
        async for token in generate_answer_stream("q", ["c"]):
            tokens.append(token)
        assert tokens == ["Hello", " world"]


# ── Gemini provider tests ──────────────────────────────────────


class TestGenerateGemini:
    @patch("app.services.llm.httpx.Client")
    def test_returns_response(self, MockClient, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "gemini")
        monkeypatch.setattr("app.services.llm.settings.gemini_chat_model", "gemini-2.5-flash")
        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "gem-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "  gemini answer  "}]}}]
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        MockClient.return_value = mock_client

        result = _generate_gemini("question", ["context"])
        assert result == "gemini answer"

    @patch("app.services.llm.httpx.Client")
    def test_generate_answer_gemini_dispatch(self, MockClient, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "gemini")
        monkeypatch.setattr("app.services.llm.settings.gemini_chat_model", "gemini-2.5-flash")
        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "gem-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "answer"}]}}]
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        MockClient.return_value = mock_client

        result = generate_answer("q", ["c"])
        assert result == "answer"


class TestGenerateGeminiStream:
    @pytest.mark.asyncio
    async def test_yields_tokens(self, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "gemini")
        monkeypatch.setattr("app.services.llm.settings.gemini_chat_model", "gemini-2.5-flash")
        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "gem-key")

        lines = [
            'data: {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}',
            'data: {"candidates": [{"content": {"parts": [{"text": " world"}]}}]}',
            "not-data-line",
        ]

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=_AsyncLineIterator(lines))
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.llm.httpx.AsyncClient", return_value=mock_client):
            tokens = []
            async for token in generate_answer_stream("q", ["c"]):
                tokens.append(token)
            assert tokens == ["hello", " world"]


# ── Describe Image tests ───────────────────────────────────────


class TestDescribeImage:
    def test_returns_empty_without_api_key(self, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "")
        result = describe_image(b"fake-image")
        assert result == ""

    @patch("app.services.llm.httpx.Client")
    def test_returns_description(self, MockClient, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "gem-key")
        monkeypatch.setattr("app.services.llm.settings.gemini_chat_model", "gemini-2.5-flash")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "  An image showing charts  "}]}}]
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        MockClient.return_value = mock_client

        result = describe_image(b"fake-image-bytes")
        assert result == "An image showing charts"

    @patch("app.services.llm.httpx.Client")
    def test_returns_empty_on_exception(self, MockClient, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "gem-key")
        monkeypatch.setattr("app.services.llm.settings.gemini_chat_model", "gemini-2.5-flash")

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("network error")
        MockClient.return_value = mock_client

        result = describe_image(b"fake-image-bytes")
        assert result == ""


# ── Health / model ready with cloud providers ──────────────────


class TestHealthCloudProviders:
    def test_ollama_health_openai_returns_true(self, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "openai")
        assert ollama_health() is True

    def test_ollama_health_gemini_returns_true(self, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "gemini")
        assert ollama_health() is True

    def test_ensure_model_ready_openai_returns_true(self, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "openai")
        assert ensure_model_ready() is True

    def test_ensure_model_ready_gemini_returns_true(self, monkeypatch):
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "gemini")
        assert ensure_model_ready() is True
