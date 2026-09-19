from pydantic import ValidationError
import pytest

from cinegate.config import SecretsSettings


_ENV_KEYS = (
    "CINEGATE_BOT_TOKEN",
    "CINEGATE_DATABASE_URL",
    "CINEGATE_WEBHOOK_SECRET",
)


def clear_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_require_all_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_secret_env(monkeypatch)
    with pytest.raises(ValidationError):
        SecretsSettings(_env_file=None)


def test_database_driver_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_secret_env(monkeypatch)
    monkeypatch.setenv("CINEGATE_BOT_TOKEN", "token")
    monkeypatch.setenv("CINEGATE_DATABASE_URL", "postgresql://localhost/cinegate")
    monkeypatch.setenv("CINEGATE_WEBHOOK_SECRET", "valid_secret")

    with pytest.raises(ValidationError):
        SecretsSettings(_env_file=None)


def test_valid_secret_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_secret_env(monkeypatch)
    monkeypatch.setenv("CINEGATE_BOT_TOKEN", "token")
    monkeypatch.setenv(
        "CINEGATE_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/cinegate",
    )
    monkeypatch.setenv("CINEGATE_WEBHOOK_SECRET", "valid_secret-123")

    settings = SecretsSettings(_env_file=None)
    assert settings.webhook_secret.get_secret_value() == "valid_secret-123"
