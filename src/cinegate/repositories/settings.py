from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.db.models import AppSetting


class SettingsRepository:
    """Read and write ordinary runtime settings stored in PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> Any | None:
        return await self._session.scalar(
            select(AppSetting.value).where(AppSetting.key == key)
        )

    async def get_int(self, key: str) -> int | None:
        value = await self.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"setting {key!r} must contain an integer")
        return value

    async def set(self, key: str, value: Any) -> None:
        statement = insert(AppSetting).values(key=key, value=value)
        statement = statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={
                "value": statement.excluded.value,
                "updated_at": statement.excluded.updated_at,
            },
        )
        await self._session.execute(statement)
