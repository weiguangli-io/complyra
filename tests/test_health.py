"""Tests for the health check endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.api.routes.health import live_check, ready_check


class TestLiveCheck:
    def test_returns_ok(self):
        result = live_check()
        assert result["status"] == "ok"


class TestReadyCheck:
    @patch("app.api.routes.health.get_redis_connection")
    @patch("app.api.routes.health.ollama_health")
    @patch("app.api.routes.health.get_qdrant_client")
    @patch("app.api.routes.health.SessionLocal")
    def test_all_healthy(self, mock_session, mock_qdrant_fn, mock_ollama, mock_redis):
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_qdrant_fn.return_value.get_collections.return_value = MagicMock(collections=[])
        mock_ollama.return_value = True
        mock_redis.return_value.ping.return_value = True

        result = ready_check()
        assert result["status"] == "ok"
        assert result["checks"]["database"]["status"] is True
        assert result["checks"]["qdrant"]["status"] is True
        assert result["checks"]["llm"]["status"] is True
        assert result["checks"]["redis"]["status"] is True
        assert "version" in result
        assert "environment" in result

    @patch("app.api.routes.health.get_redis_connection")
    @patch("app.api.routes.health.ollama_health")
    @patch("app.api.routes.health.get_qdrant_client")
    @patch("app.api.routes.health.SessionLocal")
    def test_ollama_unhealthy(self, mock_session, mock_qdrant_fn, mock_ollama, mock_redis):
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_qdrant_fn.return_value.get_collections.return_value = MagicMock(collections=[])
        mock_ollama.return_value = False
        mock_redis.return_value.ping.return_value = True

        result = ready_check()
        assert result["status"] == "degraded"
        assert result["checks"]["llm"]["status"] is False

    @patch("app.api.routes.health.get_redis_connection")
    @patch("app.api.routes.health.ollama_health")
    @patch("app.api.routes.health.get_qdrant_client")
    @patch("app.api.routes.health.SessionLocal")
    def test_db_unhealthy(self, mock_session, mock_qdrant_fn, mock_ollama, mock_redis):
        mock_session.return_value.__enter__ = MagicMock(
            side_effect=Exception("db down")
        )
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_qdrant_fn.return_value.get_collections.return_value = MagicMock(collections=[])
        mock_ollama.return_value = True
        mock_redis.return_value.ping.return_value = True

        result = ready_check()
        assert result["status"] == "degraded"
        assert result["checks"]["database"]["status"] is False

    @patch("app.api.routes.health.get_redis_connection")
    @patch("app.api.routes.health.ollama_health")
    @patch("app.api.routes.health.get_qdrant_client")
    @patch("app.api.routes.health.SessionLocal")
    def test_qdrant_unhealthy(self, mock_session, mock_qdrant_fn, mock_ollama, mock_redis):
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_qdrant_fn.return_value.get_collections.side_effect = Exception("qdrant down")
        mock_ollama.return_value = True
        mock_redis.return_value.ping.return_value = True

        result = ready_check()
        assert result["status"] == "degraded"
        assert result["checks"]["qdrant"]["status"] is False

    @patch("app.api.routes.health.get_redis_connection")
    @patch("app.api.routes.health.ollama_health")
    @patch("app.api.routes.health.get_qdrant_client")
    @patch("app.api.routes.health.SessionLocal")
    def test_redis_unhealthy(self, mock_session, mock_qdrant_fn, mock_ollama, mock_redis):
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_qdrant_fn.return_value.get_collections.return_value = MagicMock(collections=[])
        mock_ollama.return_value = True
        mock_redis.side_effect = Exception("redis down")

        result = ready_check()
        assert result["status"] == "degraded"
        assert result["checks"]["redis"]["status"] is False
