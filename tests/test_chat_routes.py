"""Tests for the chat API endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.chat import _sse_event, chat, chat_stream
from app.models.schemas import ChatRequest


class TestSseEvent:
    def test_formats_event(self):
        result = _sse_event("token", {"text": "hello"})
        assert result.startswith("event: token\n")
        assert "data:" in result
        assert result.endswith("\n\n")
        data_line = result.split("\n")[1]
        parsed = json.loads(data_line.replace("data: ", ""))
        assert parsed["text"] == "hello"

    def test_empty_data(self):
        result = _sse_event("start", {})
        assert "event: start\n" in result
        assert "data: {}" in result


class TestChat:
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.run_workflow")
    def test_completed_response(self, mock_workflow, mock_log):
        mock_workflow.return_value = {
            "retrieved": [("text1", 0.9, "doc.pdf", [1])],
            "draft_answer": "The answer",
            "approval_required": False,
            "policy_blocked": False,
            "policy_violations": [],
        }
        result = chat(
            ChatRequest(question="What?"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        assert result.status == "completed"
        assert result.answer == "The answer"
        assert len(result.retrieved) == 1
        mock_log.assert_called_once()

    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.run_workflow")
    def test_pending_approval_response(self, mock_workflow, mock_log):
        mock_workflow.return_value = {
            "retrieved": [],
            "draft_answer": "draft",
            "approval_required": True,
            "approval_id": "ap-1",
            "policy_blocked": False,
            "policy_violations": [],
        }
        result = chat(
            ChatRequest(question="What?"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        assert result.status == "pending_approval"
        assert result.approval_id == "ap-1"
        assert "pending" in result.answer.lower()

    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.run_workflow")
    def test_policy_blocked_response(self, mock_workflow, mock_log):
        mock_workflow.return_value = {
            "retrieved": [],
            "draft_answer": "secret data",
            "approval_required": False,
            "policy_blocked": True,
            "policy_violations": ["pattern1"],
        }
        result = chat(
            ChatRequest(question="What?"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        assert result.status == "completed"
        # Audit action should be chat_blocked_by_policy
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == "chat_blocked_by_policy"


class _AsyncTokenIterator:
    def __init__(self, tokens):
        self._tokens = tokens
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._tokens):
            raise StopAsyncIteration
        token = self._tokens[self._index]
        self._index += 1
        return token


class TestChatStream:
    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.search_chunks")
    async def test_stream_completed(self, mock_search, mock_stream, mock_policy, mock_log, monkeypatch):
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", False)
        mock_search.return_value = [("text1", 0.9, "doc.pdf", [1])]
        mock_stream.return_value = _AsyncTokenIterator(["Hello", " world"])
        mock_policy.return_value = MagicMock(blocked=False, matched_rules=[])

        response = await chat_stream(
            ChatRequest(question="What?"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        # Collect SSE events
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        event_text = "".join(events)
        assert "retrieve_start" in event_text
        assert "retrieve_done" in event_text
        assert "generate_start" in event_text
        assert "token" in event_text
        assert "policy_passed" in event_text
        assert "done" in event_text

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.search_chunks")
    async def test_stream_policy_blocked(self, mock_search, mock_stream, mock_policy, mock_log, monkeypatch):
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", False)
        mock_search.return_value = []
        mock_stream.return_value = _AsyncTokenIterator(["bad"])
        mock_policy.return_value = MagicMock(blocked=True, matched_rules=["rule1"])

        response = await chat_stream(
            ChatRequest(question="What?"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        event_text = "".join(events)
        assert "policy_blocked" in event_text

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.create_approval_request")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.search_chunks")
    async def test_stream_approval_required(self, mock_search, mock_stream, mock_policy, mock_create, mock_log, monkeypatch):
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", True)
        mock_search.return_value = []
        mock_stream.return_value = _AsyncTokenIterator(["ok"])
        mock_policy.return_value = MagicMock(blocked=False, matched_rules=[])
        mock_create.return_value = "ap-1"

        response = await chat_stream(
            ChatRequest(question="What?"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        event_text = "".join(events)
        assert "approval_required" in event_text
        assert "ap-1" in event_text
