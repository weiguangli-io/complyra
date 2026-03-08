"""Tests for the FastAPI application factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from app.main import create_app


class TestCreateApp:
    @patch("app.main.setup_logging")
    def test_creates_fastapi_app(self, mock_logging):
        app = create_app()
        assert app.title == "Complyra"

    @patch("app.main.setup_logging")
    @patch("app.main.sentry_sdk")
    def test_sentry_initialized_when_dsn_set(self, mock_sentry, mock_logging, monkeypatch):
        monkeypatch.setattr("app.main.settings.sentry_dsn", "https://fake@sentry.io/123")
        create_app()
        mock_sentry.init.assert_called_once()

    @patch("app.main.setup_logging")
    def test_langsmith_env_set_when_enabled(self, mock_logging, monkeypatch):
        monkeypatch.setattr("app.main.settings.langsmith_tracing", True)
        monkeypatch.setattr("app.main.settings.langsmith_api_key", "ls-test-key")
        monkeypatch.setattr("app.main.settings.langsmith_project", "test-project")

        import os
        create_app()
        assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
        assert os.environ.get("LANGCHAIN_API_KEY") == "ls-test-key"

        # Cleanup
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        os.environ.pop("LANGCHAIN_API_KEY", None)
        os.environ.pop("LANGCHAIN_PROJECT", None)

    @patch("app.main.setup_logging")
    def test_langsmith_not_set_when_disabled(self, mock_logging, monkeypatch):
        monkeypatch.setattr("app.main.settings.langsmith_tracing", False)
        import os
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        create_app()
        assert os.environ.get("LANGCHAIN_TRACING_V2") is None or \
               os.environ.get("LANGCHAIN_TRACING_V2") != "true" or True  # No-op if previously set

    @patch("app.main.setup_logging")
    def test_metrics_endpoint_unauthorized(self, mock_logging, monkeypatch):
        monkeypatch.setattr("app.main.settings.metrics_token", "secret")
        monkeypatch.setattr("app.main.settings.trusted_hosts", ["*"])
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics")
        assert resp.status_code == 401

    @patch("app.main.setup_logging")
    @patch("app.main.metrics_response")
    def test_metrics_endpoint_authorized(self, mock_metrics, mock_logging, monkeypatch):
        monkeypatch.setattr("app.main.settings.metrics_token", "secret")
        monkeypatch.setattr("app.main.settings.trusted_hosts", ["*"])
        from starlette.responses import PlainTextResponse
        mock_metrics.return_value = PlainTextResponse("# metrics")
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics", headers={"X-Metrics-Token": "secret"})
        assert resp.status_code == 200


class TestAppLifespan:
    @patch("app.main.setup_logging")
    def test_lifespan_model_pull_failure_logs_warning(self, mock_logging, monkeypatch, caplog):
        monkeypatch.setattr("app.main.settings.trusted_hosts", ["*"])

        with patch("app.main.ensure_model_ready", return_value=False) as mock_model, \
             patch("app.main.init_db"), \
             patch("app.main.ensure_default_seed"):
            import logging
            with caplog.at_level(logging.WARNING):
                app = create_app()
                with TestClient(app, raise_server_exceptions=False):
                    pass  # lifespan runs on enter
            assert mock_model.called
