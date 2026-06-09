"""Application configuration.

All settings come from environment variables (or a local .env file). Nothing
is hardcoded so the same image runs in development and production. Access the
singleton via `get_settings()` so it is parsed once and cached.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Jarvis"
    app_env: Literal["development", "production"] = "development"
    debug: bool = True
    secret_key: str = "change-me"
    cors_origins: str = "http://localhost:3000"

    # --- Logging ---
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    # --- PostgreSQL ---
    postgres_user: str = "jarvis"
    postgres_password: str = "jarvis"
    postgres_db: str = "jarvis"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # --- ChromaDB ---
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    # When running inside compose the backend reaches chroma on its internal
    # port; this overrides chroma_port if set.
    chroma_port_internal: int | None = None

    # --- LLM (Phase 2) ---
    llm_provider: Literal["openai", "ollama"] = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    # Seconds to wait for an Ollama response. Local CPU generation of a JSON
    # plan can be slow, and the first call after idle includes model load time,
    # so this is generous. Lower it if you run on a fast GPU.
    ollama_timeout: float = 300.0

    # --- Embeddings (Phase 2) ---
    # "fake" is a deterministic, dependency-free embedder for tests and local
    # runs without an API key. It is NOT semantic; switch to openai/ollama for
    # real retrieval quality.
    embedding_provider: Literal["openai", "ollama", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # --- Memory tuning (Phase 2) ---
    memory_top_k: int = 8           # semantic neighbors pulled per query
    memory_recent_k: int = 5        # most-recent structured facts pulled per query
    memory_char_budget: int = 2000  # cap on injected memory block size
    # Cosine DISTANCE thresholds (lower distance == more similar).
    memory_dup_distance: float = 0.08    # at/under this, treat as duplicate
    memory_relate_distance: float = 0.35  # at/under this, candidates are "related"

    # --- Planner (Phase 3) ---
    planner_max_steps: int = 12     # hard cap on plan length the LLM may emit

    # --- Supervisor + tools (Phase 4) ---
    tool_timeout_seconds: float = 30.0   # per tool-call execution timeout
    tool_max_attempts: int = 1           # attempts per tool call (>1 enables retry)
    risky_actions_need_approval: bool = True  # global kill-switch for the risk gate

    # --- File Agent (Phase 5) ---
    # All file operations are confined to this workspace root. Nothing outside
    # it can be read, written, or deleted.
    file_workspace_root: str = "./data/workspace"
    file_max_read_bytes: int = 1_000_000
    file_max_write_bytes: int = 5_000_000
    file_search_max_results: int = 100
    file_agent_max_iters: int = 6         # tool-calling loop cap

    # --- Coding Agent (Phase 6) ---
    # Process-level execution limits. NOTE: this is a dev-grade sandbox; in
    # production run the executor inside a disposable container / microVM.
    code_exec_cpu_seconds: int = 2
    code_exec_memory_mb: int = 256
    code_exec_timeout_seconds: float = 5.0
    code_exec_fsize_bytes: int = 10_000_000
    code_exec_nproc: int = 64
    code_exec_max_output_bytes: int = 100_000
    code_exec_allow_network: bool = False  # not enforceable at process level; see sandbox
    coding_agent_max_iters: int = 6

    # --- Browser Agent (Phase 7) ---
    browser_headless: bool = True
    browser_nav_timeout_ms: int = 15_000
    browser_max_extract_chars: int = 20_000
    # CSV allowlist of hostnames; empty means any http/https host is allowed.
    browser_allowed_domains: str = ""
    browser_search_engine: str = "duckduckgo"  # duckduckgo | bing
    browser_agent_max_iters: int = 6

    # --- Gmail + credentials (Phase 8) ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str = "http://localhost:8000/integrations/gmail/callback"
    gmail_scopes: str = (
        "https://www.googleapis.com/auth/gmail.readonly,"
        "https://www.googleapis.com/auth/gmail.send,"
        "https://www.googleapis.com/auth/gmail.compose"
    )
    gmail_max_results: int = 20
    gmail_agent_max_iters: int = 6
    # Fernet key (urlsafe base64, 32 bytes) for encrypting stored OAuth tokens.
    # If unset, a key is derived from SECRET_KEY. Set explicitly in production.
    credential_encryption_key: str | None = None

    # --- Spotify (Phase 9) ---
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    spotify_redirect_uri: str = "http://localhost:8000/integrations/spotify/callback"
    spotify_scopes: str = (
        "user-read-playback-state,user-modify-playback-state,"
        "playlist-modify-private,playlist-modify-public,user-read-private"
    )
    spotify_agent_max_iters: int = 6

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spotify_scope_list(self) -> list[str]:
        return [s.strip() for s in self.spotify_scopes.split(",") if s.strip()]

    # --- WhatsApp via Twilio (Phase 10) ---
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None          # e.g. "whatsapp:+14155238886"
    twilio_messaging_service_sid: str | None = None  # required for scheduled sends
    whatsapp_agent_max_iters: int = 6

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gmail_scope_list(self) -> list[str]:
        return [s.strip() for s in self.gmail_scopes.split(",") if s.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Sync URL for tooling that does not speak async (e.g. some Alembic setups)."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def chroma_effective_port(self) -> int:
        return self.chroma_port_internal or self.chroma_port

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
