from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from aiogram.enums import MessageEntityType
from aiogram.types import MessageEntity
from sqlalchemy import delete, func, select

from cinegate.admin.registry import AdminValidationError
from cinegate.admin.service import OwnerAdminService
from cinegate.db.models import (
    AdminAuditLog,
    AppSetting,
    MessageTemplate,
    OwnerEditSession,
)
from cinegate.db.session import Database
from cinegate.presentation.templates import TemplateRenderError, serialize_entities

DATABASE_URL = os.getenv("CINEGATE_DATABASE_URL")
OWNER_ID = 123456789


async def clean_admin_tables(database: Database) -> None:
    async with database.session() as session, session.begin():
        await session.execute(delete(AdminAuditLog))
        await session.execute(delete(OwnerEditSession))
        await session.execute(delete(AppSetting))
        await session.execute(delete(MessageTemplate))


@pytest_asyncio.fixture
async def database() -> Database:
    if not DATABASE_URL:
        pytest.skip("CINEGATE_DATABASE_URL is not configured")

    database = Database(DATABASE_URL, pool_size=3, max_overflow=0)
    await clean_admin_tables(database)
    try:
        yield database
    finally:
        await clean_admin_tables(database)
        await database.dispose()


@pytest.mark.asyncio
async def test_edit_session_survives_service_recreation(database: Database) -> None:
    first = OwnerAdminService(database)
    await first.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )

    second = OwnerAdminService(database)
    edit = await second.get_edit(OWNER_ID)

    assert edit is not None
    assert edit.edit_kind == "setting"
    assert edit.target_key == "search_result_limit"


@pytest.mark.asyncio
async def test_setting_mutation_and_audit_commit_together(database: Database) -> None:
    service = OwnerAdminService(database)
    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )

    result = await service.apply_setting_edit(
        owner_user_id=OWNER_ID,
        raw_value="7",
    )

    assert result.changed
    assert result.value == 7
    assert await service.get_edit(OWNER_ID) is None

    async with database.session() as session:
        value = await session.scalar(
            select(AppSetting.value).where(
                AppSetting.key == "search_result_limit"
            )
        )
        audit = await session.scalar(select(AdminAuditLog))

    assert value == 7
    assert audit is not None
    assert audit.action == "set"
    assert audit.target_key == "search_result_limit"
    assert audit.old_value == 6
    assert audit.new_value == 7


@pytest.mark.asyncio
async def test_same_value_update_creates_no_audit_noise(database: Database) -> None:
    service = OwnerAdminService(database)

    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )
    await service.apply_setting_edit(
        owner_user_id=OWNER_ID,
        raw_value="7",
    )

    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )
    second = await service.apply_setting_edit(
        owner_user_id=OWNER_ID,
        raw_value="7",
    )

    async with database.session() as session:
        count = await session.scalar(select(func.count(AdminAuditLog.id)))

    assert not second.changed
    assert count == 1


@pytest.mark.asyncio
async def test_invalid_setting_keeps_edit_session_active(database: Database) -> None:
    service = OwnerAdminService(database)
    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )

    with pytest.raises(AdminValidationError):
        await service.apply_setting_edit(
            owner_user_id=OWNER_ID,
            raw_value="99",
        )

    edit = await service.get_edit(OWNER_ID)
    assert edit is not None
    assert edit.target_key == "search_result_limit"

    async with database.session() as session:
        value = await session.get(AppSetting, "search_result_limit")
        audit_count = await session.scalar(select(func.count(AdminAuditLog.id)))

    assert value is None
    assert audit_count == 0


@pytest.mark.asyncio
async def test_template_entities_are_stored_and_audited(database: Database) -> None:
    service = OwnerAdminService(database)
    body = "وجدنا %count% نتيجة"
    variable_offset = len("وجدنا ".encode("utf-16-le")) // 2
    entity = MessageEntity(
        type=MessageEntityType.BOLD,
        offset=variable_offset,
        length=len("%count%".encode("utf-16-le")) // 2,
    )
    entities = serialize_entities([entity])

    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="template",
        target_key="search_results",
    )
    result = await service.apply_template_edit(
        owner_user_id=OWNER_ID,
        body=body,
        entities=entities,
    )

    assert result.changed

    async with database.session() as session:
        stored = await session.get(MessageTemplate, "search_results")
        audit = await session.scalar(
            select(AdminAuditLog).where(
                AdminAuditLog.target_key == "search_results"
            )
        )

    assert stored is not None
    assert stored.body == body
    assert stored.entities == entities
    assert audit is not None
    assert audit.new_value["body"] == body


@pytest.mark.asyncio
async def test_invalid_template_does_not_mutate_or_end_edit(database: Database) -> None:
    service = OwnerAdminService(database)
    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="template",
        target_key="welcome",
    )

    with pytest.raises(TemplateRenderError, match="unsupported"):
        await service.apply_template_edit(
            owner_user_id=OWNER_ID,
            body="Hello %movie%",
            entities=None,
        )

    edit = await service.get_edit(OWNER_ID)
    assert edit is not None

    async with database.session() as session:
        stored = await session.get(MessageTemplate, "welcome")
        audit_count = await session.scalar(select(func.count(AdminAuditLog.id)))

    assert stored is None
    assert audit_count == 0


@pytest.mark.asyncio
async def test_reset_setting_restores_default_and_audits_effective_change(
    database: Database,
) -> None:
    service = OwnerAdminService(database)
    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )
    await service.apply_setting_edit(
        owner_user_id=OWNER_ID,
        raw_value="8",
    )

    result = await service.reset_setting(
        owner_user_id=OWNER_ID,
        key="search_result_limit",
    )

    assert result.changed
    assert result.value == 6
    assert await service.get_setting_effective("search_result_limit") == 6

    async with database.session() as session:
        row = await session.get(AppSetting, "search_result_limit")
        audits = (
            await session.execute(
                select(AdminAuditLog).order_by(AdminAuditLog.id)
            )
        ).scalars().all()

    assert row is None
    assert [audit.action for audit in audits] == ["set", "reset"]


@pytest.mark.asyncio
async def test_concurrent_reset_records_single_effective_change(
    database: Database,
) -> None:
    service = OwnerAdminService(database)
    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )
    await service.apply_setting_edit(
        owner_user_id=OWNER_ID,
        raw_value="8",
    )

    first, second = await asyncio.gather(
        service.reset_setting(
            owner_user_id=OWNER_ID,
            key="search_result_limit",
        ),
        service.reset_setting(
            owner_user_id=OWNER_ID,
            key="search_result_limit",
        ),
    )

    assert sum(result.changed for result in (first, second)) == 1

    async with database.session() as session:
        reset_count = await session.scalar(
            select(func.count(AdminAuditLog.id)).where(
                AdminAuditLog.action == "reset"
            )
        )

    assert reset_count == 1



@pytest.mark.asyncio
async def test_rapid_duplicate_edit_submission_has_single_winner(
    database: Database,
) -> None:
    service = OwnerAdminService(database)
    await service.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )

    first, second = await asyncio.gather(
        service.apply_setting_edit(
            owner_user_id=OWNER_ID,
            raw_value="9",
        ),
        service.apply_setting_edit(
            owner_user_id=OWNER_ID,
            raw_value="9",
        ),
        return_exceptions=True,
    )

    successes = [
        result
        for result in (first, second)
        if not isinstance(result, Exception)
    ]
    failures = [
        result
        for result in (first, second)
        if isinstance(result, Exception)
    ]

    assert len(successes) == 1
    assert successes[0].changed
    assert len(failures) == 1
    assert isinstance(failures[0], AdminValidationError)

    async with database.session() as session:
        audit_count = await session.scalar(
            select(func.count(AdminAuditLog.id)).where(
                AdminAuditLog.target_key == "search_result_limit"
            )
        )
        value = await session.scalar(
            select(AppSetting.value).where(
                AppSetting.key == "search_result_limit"
            )
        )

    assert audit_count == 1
    assert value == 9
