"""Tests for the LangGraph workflow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.workflow import (
    WorkflowState,
    approval_node,
    draft_node,
    final_node,
    judge_node,
    retrieve_node,
    rewrite_node,
    route_after_draft,
    route_after_judge,
    run_workflow,
)


class TestRetrieveNode:
    @patch("app.services.workflow.search_chunks")
    def test_returns_matches(self, mock_search):
        mock_search.return_value = [("chunk1", 0.9, "doc.pdf", [1])]
        state: WorkflowState = {"question": "q", "tenant_id": "t1", "user_id": "u1"}
        result = retrieve_node(state)
        assert len(result["retrieved"]) == 1
        assert result["retrieved"][0][0] == "chunk1"


class TestDraftNode:
    @patch("app.services.workflow.evaluate_output_policy")
    @patch("app.services.workflow.generate_answer")
    def test_returns_draft_with_policy(self, mock_gen, mock_policy):
        mock_gen.return_value = "raw answer"
        mock_result = MagicMock()
        mock_result.answer = "raw answer"
        mock_result.blocked = False
        mock_result.matched_rules = []
        mock_policy.return_value = mock_result

        state: WorkflowState = {
            "question": "q",
            "retrieved": [("ctx", 0.9, "src", [1])],
        }
        result = draft_node(state)
        assert result["draft_answer"] == "raw answer"
        assert result["policy_blocked"] is False

    @patch("app.services.workflow.evaluate_output_policy")
    @patch("app.services.workflow.generate_answer")
    def test_policy_blocked(self, mock_gen, mock_policy):
        mock_gen.return_value = "secret: AKIAXXXXXXXXXXXXXXXX"
        mock_result = MagicMock()
        mock_result.answer = "blocked message"
        mock_result.blocked = True
        mock_result.matched_rules = ["AKIA pattern"]
        mock_policy.return_value = mock_result

        state: WorkflowState = {"question": "q", "retrieved": []}
        result = draft_node(state)
        assert result["policy_blocked"] is True
        assert len(result["policy_violations"]) == 1


class TestApprovalNode:
    @patch("app.services.workflow.create_approval_request")
    def test_creates_approval(self, mock_create):
        mock_create.return_value = "approval-123"
        state: WorkflowState = {
            "user_id": "u1",
            "tenant_id": "t1",
            "question": "q",
            "draft_answer": "answer",
        }
        result = approval_node(state)
        assert result["approval_required"] is True
        assert result["approval_id"] == "approval-123"


class TestFinalNode:
    def test_marks_no_approval(self):
        result = final_node({})
        assert result["approval_required"] is False


class TestRouteAfterDraft:
    def test_policy_blocked_goes_final(self):
        assert route_after_draft({"policy_blocked": True}) == "final"

    @patch("app.services.approval_policy.should_require_approval", return_value=True)
    def test_approval_required(self, mock_approval):
        state = {"policy_blocked": False, "tenant_id": "t1", "source_document_ids": []}
        assert route_after_draft(state) == "approval"

    @patch("app.services.approval_policy.should_require_approval", return_value=False)
    def test_no_approval_goes_final(self, mock_approval):
        state = {"policy_blocked": False, "tenant_id": "t1", "source_document_ids": []}
        assert route_after_draft(state) == "final"


class TestRouteAfterJudge:
    def test_returns_retrieve_when_sub_questions_exist(self, monkeypatch):
        monkeypatch.setattr("app.services.workflow.settings.max_retrieval_attempts", 3)
        state = {"sub_questions": ["q1", "q2"], "retrieval_attempts": 1}
        assert route_after_judge(state) == "retrieve"

    def test_returns_draft_when_no_sub_questions(self, monkeypatch):
        monkeypatch.setattr("app.services.workflow.settings.max_retrieval_attempts", 3)
        state = {"sub_questions": [], "retrieval_attempts": 1}
        assert route_after_judge(state) == "draft"

    def test_returns_draft_when_max_attempts_reached(self, monkeypatch):
        monkeypatch.setattr("app.services.workflow.settings.max_retrieval_attempts", 2)
        state = {"sub_questions": ["q1"], "retrieval_attempts": 2}
        assert route_after_judge(state) == "draft"


class TestRewriteNode:
    @patch("app.services.workflow.settings")
    def test_skips_rewrite_when_disabled(self, mock_settings):
        mock_settings.query_rewrite_enabled = False
        state: WorkflowState = {"question": "original question"}
        result = rewrite_node(state)
        assert result["rewritten_query"] == "original question"

    @patch("app.services.workflow.rewrite_query")
    @patch("app.services.workflow.settings")
    def test_rewrites_query_when_enabled(self, mock_settings, mock_rewrite):
        mock_settings.query_rewrite_enabled = True

        import asyncio
        async def fake_rewrite(q):
            return "rewritten " + q
        mock_rewrite.side_effect = fake_rewrite

        state: WorkflowState = {"question": "test question"}
        result = rewrite_node(state)
        assert result["rewritten_query"] == "rewritten test question"

    @patch("app.services.workflow.rewrite_query")
    @patch("app.services.workflow.settings")
    def test_rewrite_with_runtime_error_fallback(self, mock_settings, mock_rewrite):
        mock_settings.query_rewrite_enabled = True

        import asyncio
        async def fake_rewrite(q):
            return "rewritten"

        mock_rewrite.side_effect = fake_rewrite

        # Force RuntimeError on get_event_loop
        with patch("app.services.workflow.asyncio.get_event_loop", side_effect=RuntimeError):
            state: WorkflowState = {"question": "test"}
            result = rewrite_node(state)
            assert result["rewritten_query"] == "rewritten"


class TestRetrieveNodeRetry:
    @patch("app.services.workflow.search_chunks")
    def test_retry_with_sub_questions(self, mock_search):
        mock_search.return_value = [("new chunk", 0.8, "new.pdf", [2])]
        state: WorkflowState = {
            "question": "q",
            "tenant_id": "t1",
            "user_id": "u1",
            "retrieval_attempts": 1,
            "sub_questions": ["sub q1"],
            "all_contexts": [("existing", 0.9, "old.pdf", [1])],
        }
        result = retrieve_node(state)
        assert result["retrieval_attempts"] == 2
        # Should contain both old and new contexts
        texts = [t for t, *_ in result["all_contexts"]]
        assert "existing" in texts
        assert "new chunk" in texts

    @patch("app.services.workflow.search_chunks")
    def test_retry_deduplicates_results(self, mock_search):
        mock_search.return_value = [("existing", 0.8, "old.pdf", [1])]
        state: WorkflowState = {
            "question": "q",
            "tenant_id": "t1",
            "user_id": "u1",
            "retrieval_attempts": 1,
            "sub_questions": ["sub q1"],
            "all_contexts": [("existing", 0.9, "old.pdf", [1])],
        }
        result = retrieve_node(state)
        # Should not add duplicate
        texts = [t for t, *_ in result["all_contexts"]]
        assert texts.count("existing") == 1

    @patch("app.services.workflow.search_chunks")
    def test_first_attempt_uses_rewritten_query(self, mock_search):
        mock_search.return_value = [("chunk1", 0.9, "doc.pdf", [1])]
        state: WorkflowState = {
            "question": "original",
            "rewritten_query": "improved",
            "tenant_id": "t1",
            "user_id": "u1",
        }
        result = retrieve_node(state)
        mock_search.assert_called_once()
        # The search should use the rewritten query
        assert mock_search.call_args[0][0] == "improved"


class TestJudgeNode:
    @patch("app.services.workflow.settings")
    def test_skips_when_react_disabled(self, mock_settings):
        mock_settings.react_retrieval_enabled = False
        state: WorkflowState = {"question": "q", "retrieved": [("ctx", 0.9, "src", [1])]}
        result = judge_node(state)
        assert result["sub_questions"] == []

    @patch("app.services.workflow.settings")
    def test_skips_when_max_attempts_reached(self, mock_settings):
        mock_settings.react_retrieval_enabled = True
        mock_settings.max_retrieval_attempts = 2
        state: WorkflowState = {
            "question": "q",
            "retrieved": [("ctx", 0.9, "src", [1])],
            "retrieval_attempts": 2,
        }
        result = judge_node(state)
        assert result["sub_questions"] == []

    @patch("app.services.workflow.judge_relevance")
    @patch("app.services.workflow.settings")
    def test_returns_sub_questions_when_insufficient(self, mock_settings, mock_judge):
        mock_settings.react_retrieval_enabled = True
        mock_settings.max_retrieval_attempts = 3

        import asyncio
        async def fake_judge(q, c):
            return {"is_sufficient": False, "sub_questions": ["sq1", "sq2"]}
        mock_judge.side_effect = fake_judge

        state: WorkflowState = {
            "question": "complex question",
            "retrieved": [("ctx", 0.9, "src", [1])],
            "retrieval_attempts": 1,
        }
        result = judge_node(state)
        assert result["sub_questions"] == ["sq1", "sq2"]

    @patch("app.services.workflow.judge_relevance")
    @patch("app.services.workflow.settings")
    def test_returns_empty_when_sufficient(self, mock_settings, mock_judge):
        mock_settings.react_retrieval_enabled = True
        mock_settings.max_retrieval_attempts = 3

        import asyncio
        async def fake_judge(q, c):
            return {"is_sufficient": True, "sub_questions": []}
        mock_judge.side_effect = fake_judge

        state: WorkflowState = {
            "question": "q",
            "retrieved": [("ctx", 0.9, "src", [1])],
            "retrieval_attempts": 1,
        }
        result = judge_node(state)
        assert result["sub_questions"] == []

    @patch("app.services.workflow.judge_relevance")
    @patch("app.services.workflow.settings")
    def test_judge_with_non_running_loop(self, mock_settings, mock_judge):
        """Test the loop.run_until_complete path (loop exists but not running)."""
        mock_settings.react_retrieval_enabled = True
        mock_settings.max_retrieval_attempts = 3

        import asyncio
        async def fake_judge(q, c):
            return {"is_sufficient": True, "sub_questions": []}
        mock_judge.side_effect = fake_judge

        # Create a new event loop that is NOT running, and set it as current
        loop = asyncio.new_event_loop()
        with patch("app.services.workflow.asyncio.get_event_loop", return_value=loop):
            state: WorkflowState = {
                "question": "q",
                "retrieved": [("ctx", 0.9, "src", [1])],
                "retrieval_attempts": 1,
            }
            result = judge_node(state)
            assert result["sub_questions"] == []
        loop.close()

    @patch("app.services.workflow.judge_relevance")
    @patch("app.services.workflow.settings")
    def test_judge_runtime_error_fallback(self, mock_settings, mock_judge):
        mock_settings.react_retrieval_enabled = True
        mock_settings.max_retrieval_attempts = 3

        import asyncio
        async def fake_judge(q, c):
            return {"is_sufficient": True, "sub_questions": []}
        mock_judge.side_effect = fake_judge

        with patch("app.services.workflow.asyncio.get_event_loop", side_effect=RuntimeError):
            state: WorkflowState = {
                "question": "q",
                "retrieved": [("ctx", 0.9, "src", [1])],
                "retrieval_attempts": 1,
            }
            result = judge_node(state)
            assert result["sub_questions"] == []


class TestRewriteNodeRunningLoop:
    """Test rewrite_node when an event loop is already running."""

    @patch("app.services.workflow.rewrite_query")
    @patch("app.services.workflow.settings")
    def test_rewrite_with_running_loop(self, mock_settings, mock_rewrite):
        import asyncio
        import concurrent.futures

        mock_settings.query_rewrite_enabled = True

        async def fake_rewrite(q):
            return "rewritten from running loop"
        mock_rewrite.side_effect = fake_rewrite

        # Create a real running event loop to trigger the is_running() branch
        loop = asyncio.new_event_loop()

        async def run_in_loop():
            # Now loop.is_running() is True inside rewrite_node
            return rewrite_node({"question": "test"})

        result = loop.run_until_complete(run_in_loop())
        loop.close()
        assert result["rewritten_query"] == "rewritten from running loop"


class TestJudgeNodeRunningLoop:
    """Test judge_node when an event loop is already running."""

    @patch("app.services.workflow.judge_relevance")
    @patch("app.services.workflow.settings")
    def test_judge_with_running_loop(self, mock_settings, mock_judge):
        import asyncio

        mock_settings.react_retrieval_enabled = True
        mock_settings.max_retrieval_attempts = 3

        async def fake_judge(q, c):
            return {"is_sufficient": False, "sub_questions": ["sq1"]}
        mock_judge.side_effect = fake_judge

        loop = asyncio.new_event_loop()

        async def run_in_loop():
            return judge_node({
                "question": "q",
                "retrieved": [("ctx", 0.9, "src", [1])],
                "retrieval_attempts": 1,
            })

        result = loop.run_until_complete(run_in_loop())
        loop.close()
        assert result["sub_questions"] == ["sq1"]


class TestRunWorkflow:
    @patch("app.services.workflow.workflow_graph")
    def test_invokes_graph(self, mock_graph):
        mock_graph.invoke.return_value = {"draft_answer": "ok"}
        result = run_workflow("q", "t1", "u1")
        assert result["draft_answer"] == "ok"
        mock_graph.invoke.assert_called_once_with(
            {"question": "q", "tenant_id": "t1", "user_id": "u1"}
        )
