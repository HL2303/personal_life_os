import re
from functools import lru_cache

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://personal_life_os:local-dev-only@localhost:5432/personal_life_os"
    )
    frontend_origin: str = "http://localhost:3000"
    session_cookie_name: str = "personal_life_os_session"
    session_ttl_hours: int = 24
    session_cookie_secure: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None
    telegram_webhook_secret: SecretStr | None = None
    telegram_webhook_url: str | None = None
    telegram_link_token_ttl_minutes: int = 10
    telegram_worker_poll_seconds: int = 10
    ai_provider: str = "none"
    ai_api_key: SecretStr | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"
    ai_request_timeout_seconds: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("app_env")
    @classmethod
    def normalize_app_env(cls, value: str) -> str:
        return value.strip().casefold()

    @field_validator("ai_provider")
    @classmethod
    def validate_ai_provider(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in {"none", "openai_compatible"}:
            raise ValueError("AI_PROVIDER must be none or openai_compatible.")
        return normalized

    @field_validator("telegram_webhook_secret")
    @classmethod
    def validate_telegram_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not re.fullmatch(
            r"[A-Za-z0-9_-]{1,256}",
            value.get_secret_value(),
        ):
            raise ValueError("TELEGRAM_WEBHOOK_SECRET must use Telegram's supported characters.")
        return value

    @field_validator("telegram_bot_username")
    @classmethod
    def normalize_bot_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().removeprefix("@")
        return value or None

    @model_validator(mode="after")
    def production_requires_secure_cookie(self) -> "Settings":
        if self.app_env == "production" and not self.session_cookie_secure:
            raise ValueError("SESSION_COOKIE_SECURE must be true in production.")
        if self.session_ttl_hours < 1 or self.session_ttl_hours > 720:
            raise ValueError("SESSION_TTL_HOURS must be between 1 and 720.")
        if not 1 <= self.telegram_link_token_ttl_minutes <= 60:
            raise ValueError("TELEGRAM_LINK_TOKEN_TTL_MINUTES must be between 1 and 60.")
        if not 1 <= self.telegram_worker_poll_seconds <= 60:
            raise ValueError("TELEGRAM_WORKER_POLL_SECONDS must be between 1 and 60.")
        if not 1 <= self.ai_request_timeout_seconds <= 120:
            raise ValueError("AI_REQUEST_TIMEOUT_SECONDS must be between 1 and 120.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
