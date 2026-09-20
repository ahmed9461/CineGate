from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.db.models import MessageTemplate


@dataclass(frozen=True, slots=True)
class StoredTemplate:
    key: str
    body: str
    entities: list[dict[str, Any]] | None
    rich_message: dict[str, Any] | None


class MessageTemplateRepository:
    """Read and mutate owner-editable Telegram message templates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> StoredTemplate | None:
        row = await self._session.scalar(
            select(MessageTemplate).where(MessageTemplate.key == key)
        )
        if row is None:
            return None
        return StoredTemplate(
            key=row.key,
            body=row.body,
            entities=row.entities,
            rich_message=row.rich_message,
        )

    async def get_body(self, key: str, default: str) -> str:
        stored = await self.get(key)
        return stored.body if stored is not None else default

    async def set(
        self,
        *,
        key: str,
        body: str,
        entities: list[dict[str, Any]] | None,
        rich_message: dict[str, Any] | None = None,
    ) -> None:
        statement = insert(MessageTemplate).values(
            key=key,
            body=body,
            entities=entities,
            rich_message=rich_message,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[MessageTemplate.key],
            set_={
                "body": statement.excluded.body,
                "entities": statement.excluded.entities,
                "rich_message": statement.excluded.rich_message,
                "updated_at": statement.excluded.updated_at,
            },
        )
        await self._session.execute(statement)

    async def delete(self, key: str) -> bool:
        row = await self._session.get(MessageTemplate, key)
        if row is None:
            return False
        await self._session.delete(row)
        return True
