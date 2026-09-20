from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from cinegate.presentation.delivery import DEFAULT_DELIVERY_CAPTION
from cinegate.presentation.messages import (
    ACTIVE_REWARD_CONFLICT,
    MOVIE_UNAVAILABLE,
    NO_SEARCH_RESULTS,
    REWARD_NOT_CONFIGURED,
    REWARD_PROMPT,
    SEARCH_RESULTS,
    STALE_SEARCH,
    WELCOME,
)

ParseSetting = Callable[[str], Any]
FormatSetting = Callable[[Any], str]

_BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DURATION_RE = re.compile(
    r"^\s*(\d+)\s*"
    r"(s|sec|secs|second|seconds|m|min|mins|minute|minutes|"
    r"h|hr|hrs|hour|hours|d|day|days|"
    r"ث|ثانية|ثواني|د|دقيقة|دقائق|س|ساعة|ساعات|يوم|أيام)?\s*$",
    re.IGNORECASE,
)


class AdminValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    key: str
    label: str
    section: str
    default: Any
    parse: ParseSetting
    format: FormatSetting
    hint: str


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    key: str
    label: str
    default_body: str
    allowed_variables: frozenset[str]
    preview_values: dict[str, str]
    max_length: int = 4096


def _parse_int_range(minimum: int, maximum: int) -> ParseSetting:
    def parse(value: str) -> int:
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise AdminValidationError("أرسل رقمًا صحيحًا فقط.") from exc
        if not minimum <= parsed <= maximum:
            raise AdminValidationError(
                f"القيمة يجب أن تكون بين {minimum} و {maximum}."
            )
        return parsed

    return parse


def _parse_float_range(minimum: float, maximum: float) -> ParseSetting:
    def parse(value: str) -> float:
        try:
            parsed = float(value.strip())
        except ValueError as exc:
            raise AdminValidationError("أرسل رقمًا عشريًا صحيحًا.") from exc
        if not minimum <= parsed <= maximum:
            raise AdminValidationError(
                f"القيمة يجب أن تكون بين {minimum:g} و {maximum:g}."
            )
        return round(parsed, 4)

    return parse


def _parse_nonzero_int(value: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise AdminValidationError("أرسل معرّف Telegram رقميًا صحيحًا.") from exc
    if parsed == 0:
        raise AdminValidationError("المعرّف لا يمكن أن يكون صفرًا.")
    return parsed


def _parse_archive_channel_id(value: str) -> int:
    parsed = _parse_nonzero_int(value)
    if parsed >= 0:
        raise AdminValidationError("معرّف قناة Telegram يجب أن يكون رقمًا سالبًا.")
    return parsed


def _parse_https_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AdminValidationError("الرابط يجب أن يبدأ بـ https:// ويحتوي نطاقًا صالحًا.")
    if parsed.username or parsed.password:
        raise AdminValidationError("لا تضع بيانات دخول داخل الرابط.")
    if parsed.query or parsed.fragment:
        raise AdminValidationError("أرسل الرابط الأساسي بدون query أو #fragment.")
    return raw


def _parse_block_id(value: str) -> str:
    raw = value.strip()
    if not _BLOCK_ID_RE.fullmatch(raw):
        raise AdminValidationError(
            "Block ID يجب أن يحتوي أحرفًا/أرقامًا أو - و _ فقط."
        )
    return raw


def _parse_duration_range(minimum: int, maximum: int) -> ParseSetting:
    def parse(value: str) -> int:
        match = _DURATION_RE.fullmatch(value)
        if not match:
            raise AdminValidationError(
                "اكتب المدة مثل: 120 أو 2m أو 2 دقيقة أو 1h."
            )

        amount = int(match.group(1))
        unit = (match.group(2) or "s").casefold()
        multipliers = {
            "s": 1,
            "sec": 1,
            "secs": 1,
            "second": 1,
            "seconds": 1,
            "ث": 1,
            "ثانية": 1,
            "ثواني": 1,
            "m": 60,
            "min": 60,
            "mins": 60,
            "minute": 60,
            "minutes": 60,
            "د": 60,
            "دقيقة": 60,
            "دقائق": 60,
            "h": 3600,
            "hr": 3600,
            "hrs": 3600,
            "hour": 3600,
            "hours": 3600,
            "س": 3600,
            "ساعة": 3600,
            "ساعات": 3600,
            "d": 86400,
            "day": 86400,
            "days": 86400,
            "يوم": 86400,
            "أيام": 86400,
        }
        seconds = amount * multipliers[unit]
        if not minimum <= seconds <= maximum:
            raise AdminValidationError(
                f"المدة بعد التحويل يجب أن تكون بين {minimum} و {maximum} ثانية."
            )
        return seconds

    return parse


def _format_plain(value: Any) -> str:
    return str(value)


def _format_float(value: Any) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _format_duration(value: Any) -> str:
    seconds = int(value)
    if seconds % 86400 == 0:
        return f"{seconds // 86400} يوم"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} ساعة"
    if seconds % 60 == 0:
        return f"{seconds // 60} دقيقة"
    return f"{seconds} ثانية"


SETTINGS: dict[str, SettingDefinition] = {
    item.key: item
    for item in (
        SettingDefinition(
            "movie_delete_seconds",
            "مدة حذف الفيلم",
            "deletion",
            120,
            _parse_duration_range(5, 172000),
            _format_duration,
            "مثال: 120 أو 2 دقيقة أو 1h",
        ),
        SettingDefinition(
            "search_result_limit",
            "عدد نتائج البحث",
            "search",
            6,
            _parse_int_range(1, 10),
            _format_plain,
            "من 1 إلى 10 نتائج.",
        ),
        SettingDefinition(
            "search_similarity_threshold",
            "حساسية البحث التقريبي",
            "search",
            0.32,
            _parse_float_range(0.15, 0.95),
            _format_float,
            "قيمة بين 0.15 و 0.95.",
        ),
        SettingDefinition(
            "archive_channel_id",
            "معرّف قناة الأرشيف",
            "archive",
            None,
            _parse_archive_channel_id,
            _format_plain,
            "أرسل Channel ID الرقمي السالب.",
        ),
        SettingDefinition(
            "owner_chat_id",
            "محادثة إشعارات المالك",
            "notifications",
            None,
            _parse_nonzero_int,
            _format_plain,
            "أرسل Chat ID الذي تستقبل فيه إشعارات الأرشفة.",
        ),
        SettingDefinition(
            "public_base_url",
            "الرابط العام لـ Mini App",
            "ads",
            None,
            _parse_https_url,
            _format_plain,
            "مثال: https://cinegate.example",
        ),
        SettingDefinition(
            "adsgram_block_id",
            "AdsGram Block ID",
            "ads",
            None,
            _parse_block_id,
            _format_plain,
            "ألصق Block ID من لوحة AdsGram.",
        ),
        SettingDefinition(
            "reward_session_seconds",
            "مدة جلسة الإعلان",
            "ads",
            600,
            _parse_duration_range(60, 3600),
            _format_duration,
            "من دقيقة إلى ساعة.",
        ),
        SettingDefinition(
            "miniapp_init_data_max_age_seconds",
            "صلاحية تحقق Mini App",
            "ads",
            600,
            _parse_duration_range(60, 3600),
            _format_duration,
            "من دقيقة إلى ساعة.",
        ),
    )
}


TEMPLATES: dict[str, TemplateDefinition] = {
    item.key: item
    for item in (
        TemplateDefinition(
            "welcome",
            "رسالة البداية",
            WELCOME,
            frozenset(),
            {},
        ),
        TemplateDefinition(
            "search_results",
            "رسالة نتائج البحث",
            SEARCH_RESULTS,
            frozenset({"%count%"}),
            {"%count%": "3"},
        ),
        TemplateDefinition(
            "search_no_results",
            "رسالة عدم وجود نتائج",
            NO_SEARCH_RESULTS,
            frozenset(),
            {},
        ),
        TemplateDefinition(
            "reward_prompt",
            "رسالة مشاهدة الإعلان",
            REWARD_PROMPT,
            frozenset({"%movie%", "%quality%"}),
            {"%movie%": "Interstellar", "%quality%": "1080p"},
        ),
        TemplateDefinition(
            "delivery_caption",
            "وصف تسليم الفيلم",
            DEFAULT_DELIVERY_CAPTION,
            frozenset({"%movie%", "%year%", "%quality%", "%time%"}),
            {
                "%movie%": "Top Gun",
                "%year%": "1986",
                "%quality%": "720p",
                "%time%": "120 ثانية",
            },
            max_length=1024,
        ),
        TemplateDefinition(
            "movie_unavailable",
            "رسالة تعذر فتح الفيلم",
            MOVIE_UNAVAILABLE,
            frozenset(),
            {},
        ),
        TemplateDefinition(
            "stale_search",
            "رسالة انتهاء صلاحية النتيجة",
            STALE_SEARCH,
            frozenset(),
            {},
        ),
        TemplateDefinition(
            "reward_not_configured",
            "رسالة الإعلانات غير المجهزة",
            REWARD_NOT_CONFIGURED,
            frozenset(),
            {},
        ),
        TemplateDefinition(
            "active_reward_conflict",
            "رسالة وجود طلب إعلان نشط",
            ACTIVE_REWARD_CONFLICT,
            frozenset({"%quality%"}),
            {"%quality%": "720p"},
        ),
    )
}


def get_setting_definition(key: str) -> SettingDefinition:
    try:
        return SETTINGS[key]
    except KeyError as exc:
        raise AdminValidationError("إعداد غير معروف.") from exc


def get_template_definition(key: str) -> TemplateDefinition:
    try:
        return TEMPLATES[key]
    except KeyError as exc:
        raise AdminValidationError("قالب غير معروف.") from exc
