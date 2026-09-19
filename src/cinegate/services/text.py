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
_WORD_RE = re.compile(r"\w", re.UNICODE)

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


def extract_release_year(text: str | None) -> int | None:
    """Return the trailing year token only when text also contains a title.

    This keeps year-only movie titles such as "1917" from being mistaken for
    release metadata, while "1917 2019" correctly yields release year 2019.
    """

    if not text:
        return None

    matches = list(_YEAR_RE.finditer(text))
    if not matches:
        return None

    last = matches[-1]
    without_last = f"{text[: last.start()]} {text[last.end() :]}"
    cleaned = _QUALITY_RE.sub(" ", without_last)
    cleaned = _BOT_USERNAME_RE.sub(" ", cleaned)
    cleaned = _PUNCTUATION_RE.sub(" ", cleaned)
    if not _WORD_RE.search(cleaned):
        return None

    return int(last.group(1))


def extract_quality(text: str | None) -> str | None:
    if not text:
        return None
    match = _QUALITY_RE.search(text)
    return match.group(1).lower() if match else None


def strip_year(text: str) -> str:
    matches = list(_YEAR_RE.finditer(text))
    if not matches:
        return _collapse_spaces(text)

    last = matches[-1]
    candidate = f"{text[: last.start()]} {text[last.end() :]}"
    if not _WORD_RE.search(_PUNCTUATION_RE.sub(" ", candidate)):
        return _collapse_spaces(text)
    return _collapse_spaces(candidate)


def remove_quality_token(text: str) -> str:
    return _collapse_spaces(_QUALITY_RE.sub(" ", text)).strip()


def normalize_title(title: str | None) -> str:
    if not title:
        return ""

    value = unicodedata.normalize("NFKC", title).casefold()
    value = _BOT_USERNAME_RE.sub(" ", value)
    value = value.replace("&", " and ").replace("_", " ")
    value = _QUALITY_RE.sub(" ", value)
    value = strip_year(value)
    value = _PUNCTUATION_RE.sub(" ", value)

    tokens = [token for token in _collapse_spaces(value).split(" ") if token]
    tokens = [token for token in tokens if token not in _NOISE_WORDS]
    return " ".join(tokens)


def clean_display_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", title)
    value = _BOT_USERNAME_RE.sub(" ", value)
    value = _QUALITY_RE.sub(" ", value)
    value = strip_year(value)
    return _collapse_spaces(value).strip(" -–—:：")


def strip_bot_usernames(text: str) -> str:
    return _BOT_USERNAME_RE.sub(" ", text)


def _collapse_spaces(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()
