"""Application configuration via environment variables.

All settings are read from environment variables prefixed with ``APP_``
(e.g. ``APP_JWT_SECRET_KEY``). A ``.env`` file is also loaded if present.
"""

import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Complyra application.

    Settings are grouped into logical sections: general, auth, CORS,
    vector DB, embeddings, LLM, RAG, policy, observability, database,
    session, queue, and ingestion.
    """

    # ── General ──────────────────────────────────────────────────────
    app_name: str = "Complyra"
    env: str = "dev"
    api_prefix: str = "/api"
    log_level: str = "INFO"
    log_format: str = "json"

    # ── Authentication ─────────────────────────────────────────────
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    demo_username: str = "demo"
    demo_password_hash: str = ""
    demo_password: str = ""

    # ── CORS / Security ────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1"]

    # ── Vector Database (Qdrant) ───────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "complyra_private_kb"

    # ── Embeddings ────────────────────────────────────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_provider: str = "sentence-transformers"  # "sentence-transformers" | "openai" | "gemini"
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 384  # 384 for BGE-small, 1536 for OpenAI, 768 for Gemini
    gemini_api_key: str = ""
    gemini_embedding_model: str = "text-embedding-004"

    # ── LLM ──────────────────────────────────────────────────────
    llm_provider: str = "ollama"  # "ollama" | "openai" | "gemini"
    openai_chat_model: str = "gpt-4o-mini"
    gemini_chat_model: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b-instruct"
    ollama_prepull: bool = True
    ollama_timeout_seconds: int = 60

    # ── Query Rewrite ──────────────────────────────────────────────
    query_rewrite_enabled: bool = True

    # ── ReAct Retrieval ────────────────────────────────────────────
    react_retrieval_enabled: bool = True
    max_retrieval_attempts: int = 3

    # ── RAG Parameters ─────────────────────────────────────────────
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 4

    default_tenant_id: str = "default"

    # ── Approval & Output Policy ───────────────────────────────────
    require_approval: bool = True
    output_policy_enabled: bool = True
    output_policy_block_message: str = (
        "The generated response was withheld due to policy checks. "
        "Please contact an administrator."
    )
    output_policy_block_patterns: list[str] = [
        r"AKIA[0-9A-Z]{16}",
        r"ASIA[0-9A-Z]{16}",
        r"(?:sk|rk)-[A-Za-z0-9]{20,}",
        r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----",
        r"(?<![A-Za-z0-9_])(password|passwd|pwd)\s*[:=]\s*\S+",
    ]

    # ── Observability (LangSmith) ──────────────────────────────────
    langsmith_api_key: str = ""
    langsmith_project: str = "complyra"
    langsmith_tracing: bool = False

    # ── Observability (Sentry / Prometheus) ─────────────────────────
    sentry_dsn: str = ""
    sentry_environment: str = "dev"
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    metrics_token: str = ""

    # ── Database ──────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/app.db"

    # ── Session / Cookies ──────────────────────────────────────────
    session_cookie_name: str = "complyra_token"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str = ""

    # ── Queue / Ingestion ──────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    ingest_queue_name: str = "ingest"
    ingest_async_enabled: bool = True
    ingest_max_file_size_mb: int = 20
    ingest_storage_path: str = "./data/uploads"
    ingest_allowed_extensions: list[str] = ["pdf", "txt", "md", "png", "jpg", "jpeg"]

    # ── OCR ─────────────────────────────────────────────────────────
    ocr_enabled: bool = True
    ocr_language: str = "eng+chi_sim"
    ocr_min_text_threshold: int = 50
    chunking_strategy: str = "smart"  # "smart" | "fixed"

    # ── Hybrid Search ──────────────────────────────────────────────
    hybrid_search_enabled: bool = True

    # ── Multimodal ─────────────────────────────────────────────────
    multimodal_enabled: bool = False

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        case_sensitive=False,
    )

    @field_validator("cors_origins", "trusted_hosts", "ingest_allowed_extensions", mode="before")
    @classmethod
    def _parse_comma_separated_values(cls, value):
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",")]
            return [item for item in items if item]
        return value

    @field_validator("output_policy_block_patterns", mode="before")
    @classmethod
    def _parse_output_policy_patterns(cls, value):
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            if "||" in raw:
                return [item.strip() for item in raw.split("||") if item.strip()]
            return [raw]
        return value


settings = Settings()
