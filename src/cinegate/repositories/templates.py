from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.db.models import MessageTemplate


class MessageTemplateRepository:
    """Read owner-editable message bodies with safe application defaults."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_body(self, key: str, default: str) -> str:
        body = await self._session.scalar(
            select(MessageTemplate.body).where(MessageTemplate.key == key)
        )
        return body if body is not None else default
