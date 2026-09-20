from __future__ import annotations

from typing import Any

from cinegate.admin.diagnostics import DiagnosticsSnapshot
from cinegate.admin.registry import SettingDefinition, TemplateDefinition

_SECTION_TITLES = {
    "deletion": "⏱ حذف الأفلام",
    "search": "🔎 إعدادات البحث",
    "ads": "📢 الإعلانات و Mini App",
    "archive": "🗂 الأرشيف",
    "notifications": "🔔 الإشعارات",
}


def admin_main_text() -> str:
    return (
        "⚙️ لوحة تحكم CineGate\n\n"
        "من هنا تقدر تغيّر إعدادات التشغيل والرسائل بدون تعديل الملفات "
        "أو إعادة تشغيل المشروع."
    )


def settings_section_text(
    section: str,
    values: dict[str, Any],
    definitions: tuple[SettingDefinition, ...],
) -> str:
    title = _SECTION_TITLES.get(section, "⚙️ الإعدادات")
    lines = [title, ""]
    for definition in definitions:
        value = values.get(definition.key, definition.default)
        lines.append(
            f"• {definition.label}: {_format_setting(definition, value)}"
        )
    lines.append("")
    lines.append("اختر الإعداد الذي تريد تعديله.")
    return "\n".join(lines)


def setting_detail_text(
    definition: SettingDefinition,
    value: Any,
) -> str:
    rendered = _format_setting(definition, value)
    return (
        f"⚙️ {definition.label}\n\n"
        f"القيمة الحالية: {rendered}\n\n"
        f"{definition.hint}"
    )


def setting_edit_prompt(
    definition: SettingDefinition,
    value: Any,
) -> str:
    rendered = _format_setting(definition, value)
    return (
        f"✏️ تعديل: {definition.label}\n\n"
        f"القيمة الحالية: {rendered}\n"
        f"{definition.hint}\n\n"
        "أرسل القيمة الجديدة الآن."
    )


def templates_list_text() -> str:
    return (
        "📝 الرسائل والقوالب\n\n"
        "اختر الرسالة التي تريد تعديلها. "
        "يمكنك إرسال النص بالتنسيق الذي تريده وسيحفظ CineGate التنسيق."
    )


def template_detail_text(
    definition: TemplateDefinition,
    body: str,
) -> str:
    variables = _format_variables(definition)
    excerpt = _excerpt(body, 2400)
    return (
        f"📝 {definition.label}\n\n"
        f"المتغيرات المتاحة: {variables}\n\n"
        "النص الحالي:\n"
        f"{excerpt}"
    )


def template_edit_prompt(definition: TemplateDefinition) -> str:
    variables = _format_variables(definition)
    return (
        f"✏️ تعديل: {definition.label}\n\n"
        f"المتغيرات المتاحة: {variables}\n\n"
        "أرسل الرسالة الجديدة الآن بنفس التنسيق الذي تريده "
        "(عريض، مائل، spoiler وغيرها).\n"
        "لا تغيّر أسماء المتغيرات المكتوبة بين %...%."
    )


def mutation_confirmation(*, changed: bool, label: str) -> str:
    if changed:
        return f"✅ تم حفظ {label}."
    return f"✅ القيمة لم تتغير: {label}."


def admin_status_text(
    *,
    settings: dict[str, Any],
    diagnostics: DiagnosticsSnapshot,
) -> str:
    archive_ready = settings.get("archive_channel_id") is not None
    ads_ready = bool(
        settings.get("public_base_url")
        and settings.get("adsgram_block_id")
    )
    notifications_ready = settings.get("owner_chat_id") is not None

    text = (
        "📊 حالة CineGate\n\n"
        f"{_mark(archive_ready)} الأرشيف\n"
        f"{_mark(ads_ready)} الإعلانات و Mini App\n"
        f"{_mark(notifications_ready)} إشعارات المالك\n\n"
        f"🎬 الأفلام المفهرسة: {diagnostics.indexed_movies}\n"
        f"🎞 ملفات الجودة: {diagnostics.qualities}\n"
        f"🎁 جلسات Reward النشطة: {diagnostics.active_rewards}\n"
        f"⏳ رسائل بانتظار الحذف: {diagnostics.sent_waiting_delete}\n"
        f"⚠️ حذف فشل نهائيًا: {diagnostics.delete_failed}\n"
        f"🧾 تغييرات إدارية مسجلة: {diagnostics.audit_entries}"
    )

    if diagnostics.latest_import is not None:
        latest = diagnostics.latest_import
        text += (
            "\n\n📦 آخر استيراد تاريخي"
            f"\nالحالة: {latest.status}"
            f"\nتم النقل: {latest.copied_messages}"
            f"\nتم الاسترجاع: {latest.reconciled_messages}"
            f"\nتمت الفهرسة: {latest.reindexed_messages}"
            f"\nمفقود: {latest.missing_archive_messages}"
        )

    return text


def diagnostics_text(snapshot: DiagnosticsSnapshot) -> str:
    lines = [
        "🩺 تشخيص CineGate",
        "",
        f"✅ Indexed: {snapshot.indexed_movies}",
        f"🕓 Pending: {snapshot.pending_movies}",
        f"🟠 Orphan: {snapshot.orphan_movies}",
        f"🟡 Ambiguous: {snapshot.ambiguous_movies}",
        f"🎞 Qualities: {snapshot.qualities}",
        f"🎁 Reward نشطة: {snapshot.active_rewards}",
        f"💰 Reward جاهزة للتسليم: {snapshot.rewarded_waiting_delivery}",
        f"🗑 بانتظار الحذف: {snapshot.sent_waiting_delete}",
        f"❌ delete_failed: {snapshot.delete_failed}",
        f"🧾 Audit: {snapshot.audit_entries}",
    ]

    if snapshot.problem_movies:
        lines.extend(["", "أحدث مشاكل الفهرسة:"])
        for movie in snapshot.problem_movies:
            lines.append(
                f"• #{movie.movie_id} {movie.title} — {movie.status} "
                f"(poster {movie.poster_message_id})"
            )

    if snapshot.failed_deletions:
        lines.extend(["", "أحدث عمليات الحذف الفاشلة:"])
        for delivery in snapshot.failed_deletions:
            error = _excerpt(delivery.last_error or "سبب غير معروف", 120)
            lines.append(
                f"• Delivery #{delivery.delivery_id} "
                f"— user {delivery.telegram_user_id} "
                f"— msg {delivery.telegram_message_id or '-'}\n"
                f"  {error}"
            )

    if snapshot.latest_import is not None:
        latest = snapshot.latest_import
        lines.extend(
            [
                "",
                "آخر استيراد تاريخي:",
                f"• Job {latest.job_id}",
                f"• source {latest.source_channel_id}",
                f"• archive {latest.archive_channel_id}",
                f"• status {latest.status}",
                (
                    f"• copied {latest.copied_messages} / "
                    f"reconciled {latest.reconciled_messages} / "
                    f"reindexed {latest.reindexed_messages} / "
                    f"missing {latest.missing_archive_messages}"
                ),
            ]
        )
        if latest.last_error:
            lines.append(f"• آخر خطأ: {_excerpt(latest.last_error, 200)}")

    if snapshot.recent_audits:
        lines.extend(["", "آخر تغييرات المالك:"])
        for audit in snapshot.recent_audits:
            lines.append(
                f"• #{audit.audit_id} {audit.action} "
                f"{audit.target_type}:{audit.target_key}"
            )

    return "\n".join(lines)


def _format_setting(definition: SettingDefinition, value: Any) -> str:
    if value is None:
        return "غير مضبوط"
    try:
        return definition.format(value)
    except (TypeError, ValueError):
        return "قيمة غير صالحة حاليًا"


def _format_variables(definition: TemplateDefinition) -> str:
    if not definition.allowed_variables:
        return "لا يوجد"
    return "، ".join(sorted(definition.allowed_variables))


def _excerpt(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _mark(value: bool) -> str:
    return "✅" if value else "⚠️"
