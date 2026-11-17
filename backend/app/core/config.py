from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE = {"", "change-me", "dev-secret-change-me"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "Kokila"
    public_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://kokila:kokila@localhost:5432/kokila"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-secret-change-me"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    # Fernet key (urlsafe base64, 32 bytes). Generate: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    encryption_key: str = "Zm9yLWRldmVsb3BtZW50LW9ubHktY2hhbmdlLW1lISE="
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    cookie_secure: bool = False

    # Voice
    voice_provider: Literal["mock", "retell"] = "mock"
    retell_api_key: str = ""
    mock_webhook_secret: str = "mock-webhook-secret-dev"

    # Billing (Razorpay)
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    gst_rate_percent: int = 18

    # Google Calendar OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/integrations/google/callback"

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@kokila.local"

    # Rate limits (requests per minute)
    rate_limit_auth_per_minute: int = 10
    rate_limit_webhook_per_minute: int = 600

    raw_event_retention_days: int = 30

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if self.environment == "production":
            problems = []
            if self.jwt_secret in _INSECURE or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be a strong secret (>=32 chars)")
            if self.encryption_key == "Zm9yLWRldmVsb3BtZW50LW9ubHktY2hhbmdlLW1lISE=":
                problems.append("ENCRYPTION_KEY must be set")
            if self.voice_provider == "mock":
                problems.append("VOICE_PROVIDER=mock is not allowed in production")
            if self.voice_provider == "retell" and not self.retell_api_key:
                problems.append("RETELL_API_KEY is required when VOICE_PROVIDER=retell")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production")
            if problems:
                raise ValueError("; ".join(problems))
        return self

    @property
    def billing_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret and self.razorpay_webhook_secret)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
