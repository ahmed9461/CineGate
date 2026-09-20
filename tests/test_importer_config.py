from pathlib import Path

import pytest
from pydantic import ValidationError

from cinegate.importer.config import ImporterSettings

_KEYS = (
    "CINEGATE_DATABASE_URL",
    "CINEGATE_TELEGRAM_API_ID",
    "CINEGATE_TELEGRAM_API_HASH",
)


def clear_importer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_importer_settings_require_telegram_api_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_importer_env(monkeypatch)
    monkeypatch.setenv(
        "CINEGATE_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/cinegate",
    )

    with pytest.raises(ValidationError):
        ImporterSettings(_env_file=None)


def test_importer_api_id_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_importer_env(monkeypatch)
    monkeypatch.setenv(
        "CINEGATE_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/cinegate",
    )
    monkeypatch.setenv("CINEGATE_TELEGRAM_API_ID", "0")
    monkeypatch.setenv(
        "CINEGATE_TELEGRAM_API_HASH",
        "0123456789abcdef0123456789abcdef",
    )

    with pytest.raises(ValidationError):
        ImporterSettings(_env_file=None)


def test_importer_api_hash_must_be_32_hex_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_importer_env(monkeypatch)
    monkeypatch.setenv(
        "CINEGATE_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/cinegate",
    )
    monkeypatch.setenv("CINEGATE_TELEGRAM_API_ID", "123456")
    monkeypatch.setenv("CINEGATE_TELEGRAM_API_HASH", "not-a-valid-hash")

    with pytest.raises(ValidationError):
        ImporterSettings(_env_file=None)


def test_valid_importer_settings_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_importer_env(monkeypatch)
    monkeypatch.setenv(
        "CINEGATE_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/cinegate",
    )
    monkeypatch.setenv("CINEGATE_TELEGRAM_API_ID", "123456")
    monkeypatch.setenv(
        "CINEGATE_TELEGRAM_API_HASH",
        "0123456789abcdef0123456789abcdef",
    )

    settings = ImporterSettings(_env_file=None)

    assert settings.telegram_api_id == 123456
    assert (
        settings.telegram_api_hash.get_secret_value()
        == "0123456789abcdef0123456789abcdef"
    )


def test_gitignore_covers_default_userbot_session_material() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "*.session" in gitignore
    assert "*.session-journal" in gitignore
    assert "sessions/" in gitignore
