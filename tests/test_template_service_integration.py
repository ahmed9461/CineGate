from __future__ import annotations

import os

import pytest
import pytest_asyncio
from aiogram.enums import MessageEntityType
from aiogram.types import MessageEntity
from sqlalchemy import delete

from cinegate.db.models import MessageTemplate
from cinegate.db.session import Database
from cinegate.presentation.templates import serialize_entities
from cinegate.services.templates import TemplateService

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=2, max_overflow=0)
    async with database.session() as session, session.begin():
        await session.execute(delete(MessageTemplate))
    try:
        yield database
    finally:
        async with database.session() as session, session.begin():
            await session.execute(delete(MessageTemplate))
        await database.dispose()


@pytest.mark.asyncio
async def test_stored_formatted_template_renders_with_shifted_entities(
    database: Database,
) -> None:
    body = "وجدنا %count% نتائج"
    prefix = "وجدنا "
    entity = MessageEntity(
        type=MessageEntityType.BOLD,
        offset=len(prefix.encode("utf-16-le")) // 2,
        length=len("%count%".encode("utf-16-le")) // 2,
    )

    async with database.session() as session, session.begin():
        session.add(
            MessageTemplate(
                key="search_results",
                body=body,
                entities=serialize_entities([entity]),
            )
        )

    rendered = await TemplateService(database).render(
        "search_results",
        {"%count%": "12"},
    )

    assert rendered.text == "وجدنا 12 نتائج"
    assert len(rendered.entities) == 1
    assert rendered.entities[0].type == MessageEntityType.BOLD
    assert rendered.entities[0].length == 2


@pytest.mark.asyncio
async def test_invalid_stored_template_falls_back_to_known_default(
    database: Database,
) -> None:
    async with database.session() as session, session.begin():
        session.add(
            MessageTemplate(
                key="search_results",
                body="Invalid %unknown%",
                entities=None,
            )
        )

    rendered = await TemplateService(database).render(
        "search_results",
        {"%count%": "2"},
    )

    assert "وجدنا 2 نتائج بحث" in rendered.text
