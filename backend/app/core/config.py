"""Application configuration.

Settings are read from environment variables, falling back to a local
``.env`` file. Every value has a development default so the skeleton boots
with no configuration at all; production deployments override them.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ---
    PROJECT_NAME: str = "NLQ Analytics Platform"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = True

    # --- app database ---
    # Postgres is the target (pgvector lives here). SQLite is a no-dependency
    # fallback so the skeleton runs before Docker is available.
    DATABASE_URL: str = "sqlite+pysqlite:///./nlq_app.db"

    # --- cache ---
    REDIS_URL: str | None = None

    # --- security ---
    SECRET_KEY: str = "dev-secret-key-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    ALGORITHM: str = "HS256"
    # Fernet key used to encrypt stored target-database credentials.
    CREDENTIAL_ENCRYPTION_KEY: str | None = None

    # --- cors ---
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- llm providers (unused in phase 0, wired in phase 2) ---
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    # --- execution guardrails (phase 3) ---
    QUERY_TIMEOUT_SECONDS: int = 30
    MAX_RESULT_ROWS: int = 10_000
    MAX_CORRECTION_ATTEMPTS: int = 3

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept a comma-separated string as well as a JSON list."""
        if isinstance(v, str) and not v.strip().startswith("["):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
