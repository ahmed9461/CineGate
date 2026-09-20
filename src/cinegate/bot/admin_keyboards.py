from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from cinegate.admin.registry import SETTINGS, TEMPLATES
from cinegate.bot.admin_callbacks import (
    AdminEditCallback,
    AdminPageCallback,
    AdminSettingCallback,
    AdminTemplateCallback,
)

_SECTION_LABELS = {
    "deletion": "⏱ حذف الأفلام",
    "search": "🔎 إعدادات البحث",
    "ads": "📢 الإعلانات و Mini App",
    "archive": "🗂 الأرشيف",
    "notifications": "🔔 الإشعارات",
}


def build_admin_main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            _page_button("📝 الرسائل والقوالب", "templates", ButtonStyle.PRIMARY),
            _page_button("⏱ حذف الأفلام", "deletion", ButtonStyle.PRIMARY),
        ],
        [
            _page_button("🔎 إعدادات البحث", "search", ButtonStyle.PRIMARY),
            _page_button("📢 الإعلانات", "ads", ButtonStyle.PRIMARY),
        ],
        [
            _page_button("🗂 الأرشيف", "archive", ButtonStyle.PRIMARY),
            _page_button("🔔 الإشعارات", "notifications", ButtonStyle.PRIMARY),
        ],
        [
            _page_button("📊 الحالة", "status", ButtonStyle.SUCCESS),
            _page_button("🩺 التشخيص", "diagnostics", ButtonStyle.SUCCESS),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_settings_section_keyboard(section: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=definition.label,
                callback_data=AdminSettingCallback(
                    action="view",
                    key=definition.key,
                ).pack(),
                style=ButtonStyle.PRIMARY,
            )
        ]
        for definition in SETTINGS.values()
        if definition.section == section
    ]
    rows.append([_page_button("رجوع", "main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_setting_detail_keyboard(key: str) -> InlineKeyboardMarkup:
    section = SETTINGS[key].section
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="تعديل",
                    callback_data=AdminSettingCallback(
                        action="edit",
                        key=key,
                    ).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="استعادة الافتراضي",
                    callback_data=AdminSettingCallback(
                        action="reset",
                        key=key,
                    ).pack(),
                    style=ButtonStyle.DANGER,
                ),
            ],
            [_page_button("رجوع", section)],
        ]
    )


def build_template_list_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=definition.label,
                callback_data=AdminTemplateCallback(
                    action="view",
                    key=definition.key,
                ).pack(),
                style=ButtonStyle.PRIMARY,
            )
        ]
        for definition in TEMPLATES.values()
    ]
    rows.append([_page_button("رجوع", "main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_template_detail_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="تعديل",
                    callback_data=AdminTemplateCallback(
                        action="edit",
                        key=key,
                    ).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="معاينة",
                    callback_data=AdminTemplateCallback(
                        action="preview",
                        key=key,
                    ).pack(),
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="استعادة الافتراضي",
                    callback_data=AdminTemplateCallback(
                        action="reset",
                        key=key,
                    ).pack(),
                    style=ButtonStyle.DANGER,
                )
            ],
            [_page_button("رجوع", "templates")],
        ]
    )


def build_edit_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="إلغاء التعديل",
                    callback_data=AdminEditCallback(action="cancel").pack(),
                    style=ButtonStyle.DANGER,
                )
            ]
        ]
    )


def build_status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _page_button("تحديث", "status", ButtonStyle.SUCCESS),
                _page_button("التشخيص", "diagnostics", ButtonStyle.PRIMARY),
            ],
            [_page_button("رجوع", "main")],
        ]
    )


def build_diagnostics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _page_button("تحديث", "diagnostics", ButtonStyle.SUCCESS),
                _page_button("الحالة", "status", ButtonStyle.PRIMARY),
            ],
            [_page_button("رجوع", "main")],
        ]
    )


def section_label(section: str) -> str:
    return _SECTION_LABELS.get(section, "الإعدادات")


def _page_button(
    text: str,
    page: str,
    style: ButtonStyle | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=AdminPageCallback(page=page).pack(),
        style=style,
    )
