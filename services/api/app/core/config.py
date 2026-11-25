"""Typed settings validated at startup; fails closed on unsafe production config (§29.1)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ReasoningProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    # Isolated development-only provider. Rejected outside development/test.
    DEV_MOCK = "dev_mock"
    NONE = "none"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KOKILA_", env_file=".env", extra="ignore")

    env: Environment = Environment.DEVELOPMENT
    service_name: str = "kokila-api"
    build_id: str = "local"

    # Application role (NOBYPASSRLS). Migrations use migration_database_url.
    database_url: str = "postgresql+asyncpg://kokila_app:kokila_app_dev@localhost:5432/kokila"
    migration_database_url: str = "postgresql+asyncpg://kokila_owner:kokila_owner_dev@localhost:5432/kokila"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_issuer: str = "kokila"
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 60 * 60 * 24 * 14
    mfa_issuer_name: str = "Kokila by Manima"
    # 32-byte key (base64url) for application-level encryption of MFA secrets.
    data_encryption_key: SecretStr = SecretStr("ZGV2LW9ubHktZGF0YS1rZXktMzItYnl0ZXMtbG9uZyE=")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Providers. Model IDs live in configuration, never in domain logic (§24.1).
    reasoning_provider: ReasoningProvider = ReasoningProvider.NONE
    reasoning_fallback_provider: ReasoningProvider = ReasoningProvider.NONE
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str | None = None
    openai_realtime_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_model: str | None = None
    anthropic_version: str = "2023-06-01"
    provider_timeout_s: float = 30.0

    livekit_url: str | None = None
    livekit_api_key: str | None = None
    livekit_api_secret: SecretStr | None = None
    media_token_ttl_s: int = 600

    # Multiplies every rate-limit threshold (tests raise it; never lower than 1 in production).
    rate_limit_scale: float = Field(default=1.0, ge=1.0)
    approval_ttl_s: int = 600
    max_history_messages: int = 30
    max_turn_chars: int = 4000

    @model_validator(mode="after")
    def _fail_closed(self) -> Settings:
        prod_like = self.env in (Environment.STAGING, Environment.PRODUCTION)
        if prod_like:
            secret = self.jwt_secret.get_secret_value()
            if "dev-only" in secret or len(secret) < 32:
                raise ValueError("KOKILA_JWT_SECRET must be a strong secret outside development")
            if self.data_encryption_key.get_secret_value().startswith("ZGV2LW9ubHkt"):
                raise ValueError("KOKILA_DATA_ENCRYPTION_KEY must be set outside development")
            if "_dev@" in self.database_url:
                raise ValueError("development database credentials are not permitted outside development")
        for p in (self.reasoning_provider, self.reasoning_fallback_provider):
            if p is ReasoningProvider.DEV_MOCK and self.env not in (Environment.DEVELOPMENT, Environment.TEST):
                raise ValueError("dev_mock reasoning provider is only permitted in development/test")
        return self

    @property
    def is_dev_mock(self) -> bool:
        return self.reasoning_provider is ReasoningProvider.DEV_MOCK


@lru_cache
def get_settings() -> Settings:
    return Settings()
