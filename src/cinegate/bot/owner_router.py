from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message

from cinegate.admin.diagnostics import AdminDiagnosticsService
from cinegate.admin.presentation import (
    admin_main_text,
    admin_status_text,
    diagnostics_text,
    mutation_confirmation,
    setting_detail_text,
    setting_edit_prompt,
    settings_section_text,
    template_detail_text,
    template_edit_prompt,
    templates_list_text,
)
from cinegate.admin.registry import (
    AdminValidationError,
    SETTINGS,
    get_setting_definition,
    get_template_definition,
)
from cinegate.admin.service import EditSessionView, OwnerAdminService
from cinegate.bot.admin_callbacks import (
    AdminEditCallback,
    AdminPageCallback,
    AdminSettingCallback,
    AdminTemplateCallback,
)
from cinegate.bot.admin_keyboards import (
    build_admin_main_keyboard,
    build_diagnostics_keyboard,
    build_edit_cancel_keyboard,
    build_setting_detail_keyboard,
    build_settings_section_keyboard,
    build_status_keyboard,
    build_template_detail_keyboard,
    build_template_list_keyboard,
)
from cinegate.presentation.templates import (
    TemplateRenderError,
    serialize_entities,
)
from cinegate.services.templates import TemplateService

_SETTINGS_PAGES = frozenset(
    {"deletion", "search", "ads", "archive", "notifications"}
)


class ActiveOwnerEditFilter(BaseFilter):
    def __init__(
        self,
        *,
        owner_user_id: int,
        admin: OwnerAdminService,
    ) -> None:
        self._owner_user_id = owner_user_id
        self._admin = admin

    async def __call__(self, message: Message):
        if message.from_user is None or message.from_user.id != self._owner_user_id:
            return False
        edit = await self._admin.get_edit(self._owner_user_id)
        if edit is None:
            return False
        return {"owner_edit": edit}


def build_owner_router(
    *,
    owner_user_id: int | None,
    admin: OwnerAdminService,
    diagnostics: AdminDiagnosticsService,
    templates: TemplateService,
) -> Router:
    router = Router(name="owner")
    if owner_user_id is None:
        return router

    @router.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
    async def admin_command(message: Message) -> None:
        if not _is_owner_message(message, owner_user_id):
            return
        await admin.cancel_edit(owner_user_id)
        await message.answer(
            admin_main_text(),
            reply_markup=build_admin_main_keyboard(),
        )

    @router.callback_query(AdminPageCallback.filter())
    async def admin_page(
        callback: CallbackQuery,
        callback_data: AdminPageCallback,
        bot: Bot,
    ) -> None:
        if callback.from_user.id != owner_user_id:
            return

        await _show_page(
            callback=callback,
            page=callback_data.page,
            bot=bot,
            owner_user_id=owner_user_id,
            admin=admin,
            diagnostics=diagnostics,
        )
        await _answer_callback(callback)

    @router.callback_query(AdminSettingCallback.filter())
    async def admin_setting(
        callback: CallbackQuery,
        callback_data: AdminSettingCallback,
        bot: Bot,
    ) -> None:
        if callback.from_user.id != owner_user_id:
            return

        try:
            definition = get_setting_definition(callback_data.key)
        except AdminValidationError:
            await _answer_callback(callback)
            return

        if callback_data.action == "view":
            value = await admin.get_setting_effective(definition.key)
            await _replace_panel(
                callback=callback,
                bot=bot,
                owner_user_id=owner_user_id,
                text=setting_detail_text(definition, value),
                reply_markup=build_setting_detail_keyboard(definition.key),
            )
        elif callback_data.action == "edit":
            value = await admin.get_setting_effective(definition.key)
            await admin.begin_edit(
                owner_user_id=owner_user_id,
                edit_kind="setting",
                target_key=definition.key,
            )
            await _replace_panel(
                callback=callback,
                bot=bot,
                owner_user_id=owner_user_id,
                text=setting_edit_prompt(definition, value),
                reply_markup=build_edit_cancel_keyboard(),
            )
        elif callback_data.action == "reset":
            result = await admin.reset_setting(
                owner_user_id=owner_user_id,
                key=definition.key,
            )
            value = await admin.get_setting_effective(definition.key)
            await _replace_panel(
                callback=callback,
                bot=bot,
                owner_user_id=owner_user_id,
                text=(
                    mutation_confirmation(
                        changed=result.changed,
                        label=definition.label,
                    )
                    + "\n\n"
                    + setting_detail_text(definition, value)
                ),
                reply_markup=build_setting_detail_keyboard(definition.key),
            )

        await _answer_callback(callback)

    @router.callback_query(AdminTemplateCallback.filter())
    async def admin_template(
        callback: CallbackQuery,
        callback_data: AdminTemplateCallback,
        bot: Bot,
    ) -> None:
        if callback.from_user.id != owner_user_id:
            return

        try:
            definition = get_template_definition(callback_data.key)
        except AdminValidationError:
            await _answer_callback(callback)
            return

        if callback_data.action == "view":
            stored = await admin.get_template_effective(definition.key)
            await _replace_panel(
                callback=callback,
                bot=bot,
                owner_user_id=owner_user_id,
                text=template_detail_text(definition, stored.body),
                reply_markup=build_template_detail_keyboard(definition.key),
            )
        elif callback_data.action == "edit":
            await admin.begin_edit(
                owner_user_id=owner_user_id,
                edit_kind="template",
                target_key=definition.key,
            )
            await _replace_panel(
                callback=callback,
                bot=bot,
                owner_user_id=owner_user_id,
                text=template_edit_prompt(definition),
                reply_markup=build_edit_cancel_keyboard(),
            )
        elif callback_data.action == "preview":
            rendered = await templates.render(
                definition.key,
                definition.preview_values,
            )
            await bot.send_message(
                owner_user_id,
                rendered.text,
                entities=list(rendered.entities) or None,
            )
        elif callback_data.action == "reset":
            result = await admin.reset_template(
                owner_user_id=owner_user_id,
                key=definition.key,
            )
            stored = await admin.get_template_effective(definition.key)
            await _replace_panel(
                callback=callback,
                bot=bot,
                owner_user_id=owner_user_id,
                text=(
                    mutation_confirmation(
                        changed=result.changed,
                        label=definition.label,
                    )
                    + "\n\n"
                    + template_detail_text(definition, stored.body)
                ),
                reply_markup=build_template_detail_keyboard(definition.key),
            )

        await _answer_callback(callback)

    @router.callback_query(AdminEditCallback.filter())
    async def admin_edit_action(
        callback: CallbackQuery,
        callback_data: AdminEditCallback,
        bot: Bot,
    ) -> None:
        if callback.from_user.id != owner_user_id:
            return

        if callback_data.action == "cancel":
            await admin.cancel_edit(owner_user_id)
            await _replace_panel(
                callback=callback,
                bot=bot,
                owner_user_id=owner_user_id,
                text=admin_main_text(),
                reply_markup=build_admin_main_keyboard(),
            )
        await _answer_callback(callback)

    @router.message(
        ActiveOwnerEditFilter(
            owner_user_id=owner_user_id,
            admin=admin,
        )
    )
    async def owner_edit_input(
        message: Message,
        owner_edit: EditSessionView,
    ) -> None:
        body, entities = _message_text_and_entities(message)
        if body is None:
            await message.answer(
                "❌ أرسل رسالة نصية لإكمال التعديل.",
                reply_markup=build_edit_cancel_keyboard(),
            )
            return

        try:
            if owner_edit.edit_kind == "setting":
                result = await admin.apply_setting_edit(
                    owner_user_id=owner_user_id,
                    raw_value=body,
                )
                definition = get_setting_definition(result.target_key)
                value = await admin.get_setting_effective(result.target_key)
                text = (
                    mutation_confirmation(
                        changed=result.changed,
                        label=definition.label,
                    )
                    + "\n\n"
                    + setting_detail_text(definition, value)
                )
                keyboard = build_setting_detail_keyboard(definition.key)
            else:
                serialized = serialize_entities(entities)
                result = await admin.apply_template_edit(
                    owner_user_id=owner_user_id,
                    body=body,
                    entities=serialized,
                )
                definition = get_template_definition(result.target_key)
                stored = await admin.get_template_effective(result.target_key)
                text = (
                    mutation_confirmation(
                        changed=result.changed,
                        label=definition.label,
                    )
                    + "\n\n"
                    + template_detail_text(definition, stored.body)
                )
                keyboard = build_template_detail_keyboard(definition.key)
        except (AdminValidationError, TemplateRenderError) as exc:
            await message.answer(
                f"❌ {exc}\n\nصحح القيمة وأرسلها من جديد.",
                reply_markup=build_edit_cancel_keyboard(),
            )
            return

        await message.answer(text, reply_markup=keyboard)

    return router


async def _show_page(
    *,
    callback: CallbackQuery,
    page: str,
    bot: Bot,
    owner_user_id: int,
    admin: OwnerAdminService,
    diagnostics: AdminDiagnosticsService,
) -> None:
    if page == "main":
        await admin.cancel_edit(owner_user_id)
        await _replace_panel(
            callback=callback,
            bot=bot,
            owner_user_id=owner_user_id,
            text=admin_main_text(),
            reply_markup=build_admin_main_keyboard(),
        )
        return

    if page == "templates":
        await _replace_panel(
            callback=callback,
            bot=bot,
            owner_user_id=owner_user_id,
            text=templates_list_text(),
            reply_markup=build_template_list_keyboard(),
        )
        return

    if page in _SETTINGS_PAGES:
        definitions = tuple(
            definition
            for definition in SETTINGS.values()
            if definition.section == page
        )
        values = await admin.get_settings_effective(
            tuple(definition.key for definition in definitions)
        )
        await _replace_panel(
            callback=callback,
            bot=bot,
            owner_user_id=owner_user_id,
            text=settings_section_text(page, values, definitions),
            reply_markup=build_settings_section_keyboard(page),
        )
        return

    if page == "status":
        keys = (
            "archive_channel_id",
            "owner_chat_id",
            "public_base_url",
            "adsgram_block_id",
        )
        settings = await admin.get_settings_effective(keys)
        snapshot = await diagnostics.snapshot()
        await _replace_panel(
            callback=callback,
            bot=bot,
            owner_user_id=owner_user_id,
            text=admin_status_text(
                settings=settings,
                diagnostics=snapshot,
            ),
            reply_markup=build_status_keyboard(),
        )
        return

    if page == "diagnostics":
        snapshot = await diagnostics.snapshot()
        await _replace_panel(
            callback=callback,
            bot=bot,
            owner_user_id=owner_user_id,
            text=diagnostics_text(snapshot),
            reply_markup=build_diagnostics_keyboard(),
        )
        return

    await _replace_panel(
        callback=callback,
        bot=bot,
        owner_user_id=owner_user_id,
        text=admin_main_text(),
        reply_markup=build_admin_main_keyboard(),
    )


async def _replace_panel(
    *,
    callback: CallbackQuery,
    bot: Bot,
    owner_user_id: int,
    text: str,
    reply_markup,
) -> None:
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                text,
                reply_markup=reply_markup,
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).casefold():
                return
        except TelegramAPIError:
            pass

    await bot.send_message(
        owner_user_id,
        text,
        reply_markup=reply_markup,
    )


async def _answer_callback(callback: CallbackQuery) -> None:
    with suppress(TelegramAPIError):
        await callback.answer()


def _message_text_and_entities(message: Message):
    if message.text is not None:
        return message.text, message.entities
    if message.caption is not None:
        return message.caption, message.caption_entities
    return None, None


def _is_owner_message(message: Message, owner_user_id: int) -> bool:
    return (
        message.from_user is not None
        and message.from_user.id == owner_user_id
    )
