from __future__ import annotations

import re
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class SecretsSettings(BaseSettings):
    """Sensitive bootstrap configuration loaded from the environment.

    Normal runtime settings belong in persistent application storage and must
    not be added here merely for convenience.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CINEGATE_",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: SecretStr
    database_url: SecretStr
    webhook_secret: SecretStr
    adsgram_callback_secret: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use postgresql+asyncpg")
        return value

    @field_validator("adsgram_callback_secret")
    @classmethod
    def validate_adsgram_callback_secret(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        if len(raw) < 32 or not _WEBHOOK_SECRET_RE.fullmatch(raw):
            raise ValueError(
                "adsgram_callback_secret must be URL-safe and at least 32 characters"
            )
        return value

    @field_validator("webhook_secret")
    @classmethod
    def validate_webhook_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not _WEBHOOK_SECRET_RE.fullmatch(raw):
            raise ValueError(
                "webhook_secret must contain only letters, digits, '_' or '-' "
                "and be 1..256 characters"
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> SecretsSettings:
    return SecretsSettings()
