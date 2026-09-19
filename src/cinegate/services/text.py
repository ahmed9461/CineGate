from __future__ import annotations

import re
import unicodedata

_YEAR_RE = re.compile(r"(?<!\d)((?:19|20|21)\d{2})(?!\d)")
_QUALITY_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])#?(2160p|1080p|720p|480p|4k)(?![A-Za-z0-9])"
)
_BOT_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_]{5,32}")
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

_NOISE_WORDS = frozenset(
    {
        "film",
        "movie",
        "quality",
        "فيلم",
        "فلم",
        "الفيلم",
        "الفلم",
        "الجودة",
    }
)


def extract_year(text: str | None) -> int | None:
    if not text:
        return None
    match = _YEAR_RE.search(text)
    return int(match.group(1)) if match else None


def extract_quality(text: str | None) -> str | None:
    if not text:
        return None
    match = _QUALITY_RE.search(text)
    return match.group(1).lower() if match else None


def strip_year(text: str) -> str:
    return _collapse_spaces(_YEAR_RE.sub(" ", text)).strip()


def remove_quality_token(text: str) -> str:
    return _collapse_spaces(_QUALITY_RE.sub(" ", text)).strip()


def normalize_title(title: str | None) -> str:
    if not title:
        return ""

    value = unicodedata.normalize("NFKC", title).casefold()
    value = _BOT_USERNAME_RE.sub(" ", value)
    value = value.replace("&", " and ").replace("_", " ")
    value = _QUALITY_RE.sub(" ", value)
    value = _YEAR_RE.sub(" ", value)
    value = _PUNCTUATION_RE.sub(" ", value)

    tokens = [token for token in _collapse_spaces(value).split(" ") if token]
    tokens = [token for token in tokens if token not in _NOISE_WORDS]
    return " ".join(tokens)


def clean_display_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", title)
    value = _BOT_USERNAME_RE.sub(" ", value)
    value = _QUALITY_RE.sub(" ", value)
    value = _YEAR_RE.sub(" ", value)
    return _collapse_spaces(value).strip(" -–—:：")


def strip_bot_usernames(text: str) -> str:
    return _BOT_USERNAME_RE.sub(" ", text)


def _collapse_spaces(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()
