import pytest
from pydantic import SecretStr

from cinegate.config import SecretsSettings
from cinegate.runtime import build_runtime


@pytest.mark.asyncio
async def test_owner_router_is_wired_before_general_user_router() -> None:
    settings = SecretsSettings(
        bot_token=SecretStr(
            "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        ),
        database_url=SecretStr(
            "postgresql+asyncpg://user:password@127.0.0.1/cinegate"
        ),
        webhook_secret=SecretStr("valid_secret"),
        owner_user_id=123456789,
    )

    runtime = build_runtime(settings)
    try:
        names = [router.name for router in runtime.dispatcher.sub_routers]

        assert names == ["archive", "owner", "users"]
    finally:
        await runtime.bot.session.close()
        await runtime.database.dispose()
