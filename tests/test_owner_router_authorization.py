from __future__ import annotations

from types import SimpleNamespace

import pytest

from cinegate.bot.admin_callbacks import AdminPageCallback
from cinegate.bot.owner_router import ActiveOwnerEditFilter, build_owner_router
from cinegate.admin.service import EditSessionView

OWNER_ID = 123456789
OTHER_ID = 987654321


class FakeAdmin:
    def __init__(self) -> None:
        self.cancel_calls: list[int] = []
        self.edit: EditSessionView | None = None

    async def cancel_edit(self, owner_user_id: int) -> bool:
        self.cancel_calls.append(owner_user_id)
        self.edit = None
        return True

    async def get_edit(self, owner_user_id: int):
        if owner_user_id != OWNER_ID:
            return None
        return self.edit

    async def get_settings_effective(self, keys):
        return {key: None for key in keys}

    async def get_setting_effective(self, key):
        return None

    async def get_template_effective(self, key):
        raise AssertionError("not expected in this test")


class FakeDiagnostics:
    async def snapshot(self):
        return SimpleNamespace(
            indexed_movies=0,
            pending_movies=0,
            orphan_movies=0,
            ambiguous_movies=0,
            qualities=0,
            active_rewards=0,
            rewarded_waiting_delivery=0,
            sent_waiting_delete=0,
            delete_failed=0,
            audit_entries=0,
            problem_movies=(),
            failed_deletions=(),
        )


class FakeTemplates:
    pass


class FakeMessage:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text: str, **kwargs):
        self.answers.append((text, kwargs))
        return SimpleNamespace(message_id=100)


class FakeCallback:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.message = None
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


class FakeBot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=200)


def handler(router, observer_name: str, callback_name: str):
    observer = getattr(router, observer_name)
    return next(
        item.callback
        for item in observer.handlers
        if item.callback.__name__ == callback_name
    )


@pytest.mark.asyncio
async def test_owner_admin_command_opens_panel_and_cancels_old_edit() -> None:
    admin = FakeAdmin()
    admin.edit = EditSessionView(
        owner_user_id=OWNER_ID,
        edit_kind="setting",
        target_key="search_result_limit",
    )
    router = build_owner_router(
        owner_user_id=OWNER_ID,
        admin=admin,  # type: ignore[arg-type]
        diagnostics=FakeDiagnostics(),  # type: ignore[arg-type]
        templates=FakeTemplates(),  # type: ignore[arg-type]
    )
    command = handler(router, "message", "admin_command")
    message = FakeMessage(OWNER_ID)

    await command(message)

    assert admin.cancel_calls == [OWNER_ID]
    assert len(message.answers) == 1
    assert "لوحة تحكم CineGate" in message.answers[0][0]


@pytest.mark.asyncio
async def test_non_owner_admin_command_is_silently_ignored() -> None:
    admin = FakeAdmin()
    router = build_owner_router(
        owner_user_id=OWNER_ID,
        admin=admin,  # type: ignore[arg-type]
        diagnostics=FakeDiagnostics(),  # type: ignore[arg-type]
        templates=FakeTemplates(),  # type: ignore[arg-type]
    )
    command = handler(router, "message", "admin_command")
    message = FakeMessage(OTHER_ID)

    await command(message)

    assert message.answers == []
    assert admin.cancel_calls == []


@pytest.mark.asyncio
async def test_forged_non_owner_admin_callback_is_ignored() -> None:
    admin = FakeAdmin()
    router = build_owner_router(
        owner_user_id=OWNER_ID,
        admin=admin,  # type: ignore[arg-type]
        diagnostics=FakeDiagnostics(),  # type: ignore[arg-type]
        templates=FakeTemplates(),  # type: ignore[arg-type]
    )
    callback_handler = handler(router, "callback_query", "admin_page")
    callback = FakeCallback(OTHER_ID)
    bot = FakeBot()

    await callback_handler(
        callback,
        callback_data=AdminPageCallback(page="main"),
        bot=bot,
    )

    assert bot.sent == []
    assert callback.answers == []
    assert admin.cancel_calls == []


@pytest.mark.asyncio
async def test_active_owner_edit_filter_only_matches_owner() -> None:
    admin = FakeAdmin()
    admin.edit = EditSessionView(
        owner_user_id=OWNER_ID,
        edit_kind="template",
        target_key="welcome",
    )
    edit_filter = ActiveOwnerEditFilter(
        owner_user_id=OWNER_ID,
        admin=admin,  # type: ignore[arg-type]
    )

    owner_result = await edit_filter(FakeMessage(OWNER_ID))
    other_result = await edit_filter(FakeMessage(OTHER_ID))

    assert isinstance(owner_result, dict)
    assert owner_result["owner_edit"].target_key == "welcome"
    assert other_result is False


def test_owner_router_is_empty_when_owner_is_not_bootstrapped() -> None:
    router = build_owner_router(
        owner_user_id=None,
        admin=FakeAdmin(),  # type: ignore[arg-type]
        diagnostics=FakeDiagnostics(),  # type: ignore[arg-type]
        templates=FakeTemplates(),  # type: ignore[arg-type]
    )

    assert router.message.handlers == []
    assert router.callback_query.handlers == []
