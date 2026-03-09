"""Tests for approval policy resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetTenantApprovalMode:
    @patch("app.services.approval_policy.get_tenant_policy")
    def test_get_tenant_approval_mode_with_policy(self, mock_get):
        from app.services.approval_policy import get_tenant_approval_mode

        mock_policy = MagicMock()
        mock_policy.approval_mode = "sensitive"
        mock_get.return_value = mock_policy

        result = get_tenant_approval_mode("t1")
        assert result == "sensitive"

    @patch("app.services.approval_policy.settings")
    @patch("app.services.approval_policy.get_tenant_policy")
    def test_get_tenant_approval_mode_fallback_global_true(self, mock_get, mock_settings):
        from app.services.approval_policy import get_tenant_approval_mode

        mock_get.return_value = None
        mock_settings.require_approval = True

        result = get_tenant_approval_mode("t1")
        assert result == "all"

    @patch("app.services.approval_policy.settings")
    @patch("app.services.approval_policy.get_tenant_policy")
    def test_get_tenant_approval_mode_fallback_global_false(self, mock_get, mock_settings):
        from app.services.approval_policy import get_tenant_approval_mode

        mock_get.return_value = None
        mock_settings.require_approval = False

        result = get_tenant_approval_mode("t1")
        assert result == "none"


class TestShouldRequireApproval:
    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_should_require_approval_mode_all(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        doc = MagicMock()
        doc.approval_override = None
        doc.sensitivity = "normal"
        mock_docs.return_value = [doc]
        mock_mode.return_value = "all"

        assert should_require_approval("t1", ["doc-1"]) is True

    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_should_require_approval_mode_none(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        doc = MagicMock()
        doc.approval_override = None
        doc.sensitivity = "normal"
        mock_docs.return_value = [doc]
        mock_mode.return_value = "none"

        assert should_require_approval("t1", ["doc-1"]) is False

    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_should_require_approval_mode_sensitive_with_sensitive_doc(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        doc = MagicMock()
        doc.approval_override = None
        doc.sensitivity = "sensitive"
        mock_docs.return_value = [doc]
        mock_mode.return_value = "sensitive"

        assert should_require_approval("t1", ["doc-1"]) is True

    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_should_require_approval_mode_sensitive_with_normal_doc(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        doc = MagicMock()
        doc.approval_override = None
        doc.sensitivity = "normal"
        mock_docs.return_value = [doc]
        mock_mode.return_value = "sensitive"

        assert should_require_approval("t1", ["doc-1"]) is False

    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_doc_override_always_wins(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        doc = MagicMock()
        doc.approval_override = "always"
        doc.sensitivity = "normal"
        mock_docs.return_value = [doc]
        mock_mode.return_value = "none"

        assert should_require_approval("t1", ["doc-1"]) is True

    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_doc_override_never_with_mode_all(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        doc = MagicMock()
        doc.approval_override = "never"
        doc.sensitivity = "normal"
        mock_docs.return_value = [doc]
        mock_mode.return_value = "all"

        # "never" override skips the doc; mode "all" returns True but
        # there are no policy_docs left, so still True because mode is "all"
        assert should_require_approval("t1", ["doc-1"]) is True

    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_mixed_overrides_always_wins(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        doc1 = MagicMock()
        doc1.approval_override = "always"
        doc1.sensitivity = "normal"

        doc2 = MagicMock()
        doc2.approval_override = "never"
        doc2.sensitivity = "normal"

        mock_docs.return_value = [doc1, doc2]
        mock_mode.return_value = "none"

        assert should_require_approval("t1", ["doc-1", "doc-2"]) is True

    @patch("app.services.approval_policy.get_tenant_approval_mode")
    @patch("app.services.approval_policy.get_documents_by_ids")
    def test_no_documents_fallback_to_tenant_mode(self, mock_docs, mock_mode):
        from app.services.approval_policy import should_require_approval

        mock_docs.return_value = []
        mock_mode.return_value = "none"

        assert should_require_approval("t1", []) is False


class TestSetTenantApprovalMode:
    @patch("app.services.approval_policy.upsert_tenant_policy")
    def test_set_tenant_approval_mode(self, mock_upsert):
        from app.services.approval_policy import set_tenant_approval_mode

        mock_policy = MagicMock()
        mock_policy.approval_mode = "sensitive"
        mock_upsert.return_value = mock_policy

        result = set_tenant_approval_mode("t1", "sensitive", "admin")
        assert result.approval_mode == "sensitive"
        mock_upsert.assert_called_once_with(
            tenant_id="t1", approval_mode="sensitive", updated_by="admin",
        )
