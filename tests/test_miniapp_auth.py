from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from cinegate.services.miniapp_auth import MiniAppAuthError, validate_miniapp_user

BOT_TOKEN = "123456789:TEST_TOKEN_FOR_CINEGATE"
USER_ID = 123456789


def signed_init_data(*, auth_date: datetime, user_id: int = USER_ID) -> str:
    values = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": "Test",
                "last_name": "",
                "username": "cinegate_test",
                "language_code": "en",
                "is_premium": False,
                "allows_write_to_pm": True,
            },
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(
        f"{key}={values[key]}" for key in sorted(values)
    )
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()
    values["hash"] = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


def test_valid_signed_init_data_returns_telegram_user() -> None:
    now = datetime.now(UTC)
    init_data = signed_init_data(auth_date=now)

    user_id = validate_miniapp_user(
        bot_token=BOT_TOKEN,
        init_data=init_data,
        max_age_seconds=600,
        now=now,
    )

    assert user_id == USER_ID


def test_modified_init_data_signature_is_rejected() -> None:
    now = datetime.now(UTC)
    init_data = signed_init_data(auth_date=now)
    tampered = init_data.replace("cinegate_test", "attacker", 1)

    with pytest.raises(MiniAppAuthError, match="signature"):
        validate_miniapp_user(
            bot_token=BOT_TOKEN,
            init_data=tampered,
            max_age_seconds=600,
            now=now,
        )


def test_stale_signed_init_data_is_rejected() -> None:
    now = datetime.now(UTC)
    init_data = signed_init_data(auth_date=now - timedelta(minutes=20))

    with pytest.raises(MiniAppAuthError, match="stale"):
        validate_miniapp_user(
            bot_token=BOT_TOKEN,
            init_data=init_data,
            max_age_seconds=600,
            now=now,
        )


def test_future_signed_init_data_outside_clock_tolerance_is_rejected() -> None:
    now = datetime.now(UTC)
    init_data = signed_init_data(auth_date=now + timedelta(minutes=2))

    with pytest.raises(MiniAppAuthError, match="stale"):
        validate_miniapp_user(
            bot_token=BOT_TOKEN,
            init_data=init_data,
            max_age_seconds=600,
            now=now,
        )
