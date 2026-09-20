from __future__ import annotations

from datetime import UTC, datetime

from aiogram.utils.web_app import safe_parse_webapp_init_data


class MiniAppAuthError(ValueError):
    pass


def validate_miniapp_user(
    *,
    bot_token: str,
    init_data: str,
    max_age_seconds: int,
    now: datetime | None = None,
) -> int:
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    try:
        parsed = safe_parse_webapp_init_data(
            token=bot_token,
            init_data=init_data,
        )
    except ValueError as exc:
        raise MiniAppAuthError("invalid Telegram Mini App signature") from exc

    if parsed.user is None:
        raise MiniAppAuthError("Telegram Mini App user is missing")
    if parsed.auth_date is None:
        raise MiniAppAuthError("Telegram Mini App auth_date is missing")

    current = now or datetime.now(UTC)
    auth_date = parsed.auth_date
    if isinstance(auth_date, datetime):
        if auth_date.tzinfo is None:
            auth_date = auth_date.replace(tzinfo=UTC)
        auth_timestamp = auth_date.timestamp()
    else:
        auth_timestamp = float(auth_date)

    age_seconds = current.timestamp() - auth_timestamp
    if age_seconds < -30 or age_seconds > max_age_seconds:
        raise MiniAppAuthError("Telegram Mini App init data is stale")

    return int(parsed.user.id)
