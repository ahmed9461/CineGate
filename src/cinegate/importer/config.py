from __future__ import annotations

import re

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class _ImporterBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CINEGATE_",
        case_sensitive=False,
        extra="ignore",
    )


class ImporterDatabaseSettings(_ImporterBaseSettings):
    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        return _validate_database_url(value)


class ImporterTelegramSettings(_ImporterBaseSettings):
    telegram_api_id: int
    telegram_api_hash: SecretStr

    @field_validator("telegram_api_id")
    @classmethod
    def validate_api_id(cls, value: int) -> int:
        return _validate_api_id(value)

    @field_validator("telegram_api_hash")
    @classmethod
    def validate_api_hash(cls, value: SecretStr) -> SecretStr:
        return _validate_api_hash(value)


class ImporterSettings(_ImporterBaseSettings):
    """Full settings required by transfer/reindex/verify commands."""

    database_url: SecretStr
    telegram_api_id: int
    telegram_api_hash: SecretStr

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        return _validate_database_url(value)

    @field_validator("telegram_api_id")
    @classmethod
    def validate_api_id(cls, value: int) -> int:
        return _validate_api_id(value)

    @field_validator("telegram_api_hash")
    @classmethod
    def validate_api_hash(cls, value: SecretStr) -> SecretStr:
        return _validate_api_hash(value)


class ImporterProgressSettings(_ImporterBaseSettings):
    """Optional Bot API credential used only for owner progress reporting."""

    bot_token: SecretStr | None = None


def _validate_database_url(value: SecretStr) -> SecretStr:
    if not value.get_secret_value().startswith("postgresql+asyncpg://"):
        raise ValueError("database_url must use postgresql+asyncpg")
    return value


def _validate_api_id(value: int) -> int:
    if value <= 0:
        raise ValueError("telegram_api_id must be positive")
    return value


def _validate_api_hash(value: SecretStr) -> SecretStr:
    if not _API_HASH_RE.fullmatch(value.get_secret_value()):
        raise ValueError("telegram_api_hash must be a 32-character hex value")
    return value
