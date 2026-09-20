from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiogram.enums import MessageEntityType
from aiogram.types import MessageEntity
from sqlalchemy import delete, func, select

from cinegate.admin.diagnostics import AdminDiagnosticsService
from cinegate.admin.service import OwnerAdminService
from cinegate.bot.admin_callbacks import (
    AdminSettingCallback,
    AdminTemplateCallback,
)
from cinegate.bot.owner_router import build_owner_router
from cinegate.db.models import (
    AdminAuditLog,
    AppSetting,
    MessageTemplate,
    OwnerEditSession,
)
from cinegate.db.session import Database
from cinegate.services.templates import TemplateService

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

    database = Database(DATABASE_URL, pool_size=2, max_overflow=0)
    await clean_admin_tables(database)
    try:
        yield database
    finally:
        await clean_admin_tables(database)
        await database.dispose()


class FakeCallback:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=OWNER_ID)
        self.message = None
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


class FakeBot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        sent = SimpleNamespace(
            message_id=1000 + len(self.sent),
            chat_id=chat_id,
            text=text,
            **kwargs,
        )
        self.sent.append(sent)
        return sent


class FakeEditMessage:
    def __init__(self, text: str, entities=None) -> None:
        self.from_user = SimpleNamespace(id=OWNER_ID)
        self.text = text
        self.caption = None
        self.entities = entities
        self.caption_entities = None
        self.answers = []

    async def answer(self, text: str, **kwargs):
        sent = SimpleNamespace(
            message_id=2000 + len(self.answers),
            text=text,
            **kwargs,
        )
        self.answers.append(sent)
        return sent


def handler(router, observer_name: str, callback_name: str):
    observer = getattr(router, observer_name)
    return next(
        item.callback
        for item in observer.handlers
        if item.callback.__name__ == callback_name
    )


@pytest.mark.asyncio
async def test_setting_edit_button_then_owner_message_persists_value_and_audit(
    database: Database,
) -> None:
    admin = OwnerAdminService(database)
    router = build_owner_router(
        owner_user_id=OWNER_ID,
        admin=admin,
        diagnostics=AdminDiagnosticsService(database),
        templates=TemplateService(database),
    )
    bot = FakeBot()

    setting_handler = handler(router, "callback_query", "admin_setting")
    callback = FakeCallback()
    await setting_handler(
        callback,
        callback_data=AdminSettingCallback(
            action="edit",
            key="search_result_limit",
        ),
        bot=bot,
    )

    edit = await admin.get_edit(OWNER_ID)
    assert edit is not None
    assert edit.target_key == "search_result_limit"
    assert bot.sent
    assert "أرسل القيمة الجديدة" in bot.sent[-1].text

    edit_handler = handler(router, "message", "owner_edit_input")
    message = FakeEditMessage("8")
    await edit_handler(message, owner_edit=edit)

    assert message.answers
    assert "تم حفظ" in message.answers[-1].text
    assert await admin.get_edit(OWNER_ID) is None

    async with database.session() as session:
        value = await session.scalar(
            select(AppSetting.value).where(
                AppSetting.key == "search_result_limit"
            )
        )
        audit_count = await session.scalar(
            select(func.count(AdminAuditLog.id)).where(
                AdminAuditLog.target_key == "search_result_limit"
            )
        )

    assert value == 8
    assert audit_count == 1


@pytest.mark.asyncio
async def test_invalid_owner_edit_keeps_session_and_requests_correction(
    database: Database,
) -> None:
    admin = OwnerAdminService(database)
    router = build_owner_router(
        owner_user_id=OWNER_ID,
        admin=admin,
        diagnostics=AdminDiagnosticsService(database),
        templates=TemplateService(database),
    )

    await admin.begin_edit(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )
    edit = await admin.get_edit(OWNER_ID)
    assert edit is not None

    edit_handler = handler(router, "message", "owner_edit_input")
    message = FakeEditMessage("999")
    await edit_handler(message, owner_edit=edit)

    assert message.answers
    assert "صحح القيمة" in message.answers[-1].text
    assert await admin.get_edit(OWNER_ID) is not None

    async with database.session() as session:
        setting = await session.get(AppSetting, "search_result_limit")
        audit_count = await session.scalar(select(func.count(AdminAuditLog.id)))

    assert setting is None
    assert audit_count == 0



@pytest.mark.asyncio
async def test_template_edit_preview_and_reset_preserve_formatting(
    database: Database,
) -> None:
    admin = OwnerAdminService(database)
    templates = TemplateService(database)
    router = build_owner_router(
        owner_user_id=OWNER_ID,
        admin=admin,
        diagnostics=AdminDiagnosticsService(database),
        templates=templates,
    )
    bot = FakeBot()

    template_handler = handler(router, "callback_query", "admin_template")
    edit_handler = handler(router, "message", "owner_edit_input")

    callback = FakeCallback()
    await template_handler(
        callback,
        callback_data=AdminTemplateCallback(
            action="edit",
            key="search_results",
        ),
        bot=bot,
    )

    edit = await admin.get_edit(OWNER_ID)
    assert edit is not None
    body = "وجدنا %count% نتيجة"
    prefix_units = len("وجدنا ".encode("utf-16-le")) // 2
    token_units = len("%count%".encode("utf-16-le")) // 2
    entity = MessageEntity(
        type=MessageEntityType.BOLD,
        offset=prefix_units,
        length=token_units,
    )

    message = FakeEditMessage(body, entities=[entity])
    await edit_handler(message, owner_edit=edit)

    stored = await admin.get_template_effective("search_results")
    assert stored.body == body
    assert stored.entities is not None

    preview_callback = FakeCallback()
    await template_handler(
        preview_callback,
        callback_data=AdminTemplateCallback(
            action="preview",
            key="search_results",
        ),
        bot=bot,
    )

    preview = bot.sent[-1]
    assert preview.text == "وجدنا 3 نتيجة"
    assert preview.entities is not None
    assert len(preview.entities) == 1
    assert preview.entities[0].type == MessageEntityType.BOLD
    assert preview.entities[0].length == 1

    reset_callback = FakeCallback()
    await template_handler(
        reset_callback,
        callback_data=AdminTemplateCallback(
            action="reset",
            key="search_results",
        ),
        bot=bot,
    )

    reset = await admin.get_template_effective("search_results")
    assert "وجدنا %count% نتائج بحث" in reset.body
    assert reset.entities is None

    async with database.session() as session:
        audits = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.target_key == "search_results")
                .order_by(AdminAuditLog.id)
            )
        ).scalars().all()

    assert [audit.action for audit in audits] == ["set", "reset"]


@pytest.mark.asyncio
async def test_template_preview_uses_default_when_no_custom_template(
    database: Database,
) -> None:
    admin = OwnerAdminService(database)
    router = build_owner_router(
        owner_user_id=OWNER_ID,
        admin=admin,
        diagnostics=AdminDiagnosticsService(database),
        templates=TemplateService(database),
    )
    bot = FakeBot()

    template_handler = handler(router, "callback_query", "admin_template")
    callback = FakeCallback()
    await template_handler(
        callback,
        callback_data=AdminTemplateCallback(
            action="preview",
            key="reward_prompt",
        ),
        bot=bot,
    )

    assert bot.sent
    assert "Interstellar" in bot.sent[-1].text
    assert "1080p" in bot.sent[-1].text
