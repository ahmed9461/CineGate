from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from cinegate.domain.archive import (
    ArchiveMessage,
    GroupStatus,
    MediaKind,
    ParsedMovieGroup,
    ParsedQuality,
    ParserStyle,
)
from cinegate.services.text import (
    clean_display_title,
    extract_quality,
    extract_year,
    normalize_title,
    remove_quality_token,
    strip_bot_usernames,
    strip_year,
)

_FIELD_RE = re.compile(r"^\s*([^:：\n]{1,32})\s*[:：]\s*(.+?)\s*$")
_FOLLOWER_TAG = "#طلب_المتابعين"

_TITLE_LABELS = frozenset({"الفيلم", "فيلم", "فلم", "الفلم"})
_LEGACY_ONLY_TITLE_LABELS = frozenset({"فيلم", "فلم", "الفلم"})
_SUPPORTING_POSTER_FIELDS = frozenset(
    {"التصنيف", "النوع", "البلد", "اللغة", "الترجمة", "السنة", "التقييم", "القصة"}
)

_ACCEPT_THRESHOLD = 60
_AMBIGUOUS_THRESHOLD = 40
_MAX_PARSED_CAPTION_CHARS = 8192


@dataclass(frozen=True, slots=True)
class _PosterCandidate:
    message: ArchiveMessage
    raw_title: str
    display_title: str
    normalized_title: str
    year: int | None
    style: ParserStyle
    confidence: int


@dataclass(frozen=True, slots=True)
class _QualityCandidate:
    message: ArchiveMessage
    quality: str
    raw_title: str | None
    normalized_title: str | None
    year: int | None


@dataclass(slots=True)
class _GroupBuilder:
    poster: _PosterCandidate
    qualities: dict[str, ParsedQuality] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    ambiguous_candidates: int = 0
    messages_since_poster: int = 0
    noise_messages: int = 0


class ArchiveParser:
    """Parse ordered Telegram archive messages into movie groups.

    Parsing is deterministic and stateless. Sequence is the primary grouping
    signal; title/year similarity only adjusts confidence.
    """

    def __init__(self, *, max_noise_messages: int = 1) -> None:
        if max_noise_messages < 0:
            raise ValueError("max_noise_messages cannot be negative")
        self._max_noise_messages = max_noise_messages

    def parse(self, messages: Iterable[ArchiveMessage]) -> tuple[ParsedMovieGroup, ...]:
        groups: list[ParsedMovieGroup] = []
        current: _GroupBuilder | None = None

        for message in sorted(messages, key=lambda item: item.message_id):
            poster = _detect_poster(message)
            if poster is not None:
                if current is not None:
                    groups.append(_finalize_group(current))
                current = _GroupBuilder(poster=poster)
                continue

            quality = _detect_quality(message)
            if quality is not None:
                if current is None:
                    continue

                current.messages_since_poster += 1
                score = _score_quality(
                    poster=current.poster,
                    quality=quality,
                    distance=current.messages_since_poster,
                )

                if score >= _ACCEPT_THRESHOLD:
                    parsed = ParsedQuality(
                        message_id=quality.message.message_id,
                        quality=quality.quality,
                        raw_caption=quality.message.caption or "",
                        raw_title=quality.raw_title,
                        normalized_title=quality.normalized_title,
                        year=quality.year,
                        confidence=score,
                    )
                    previous = current.qualities.get(quality.quality)
                    if previous is None or parsed.message_id > previous.message_id:
                        if previous is not None:
                            current.diagnostics.append(
                                f"duplicate_quality_replaced:{quality.quality}:"
                                f"{previous.message_id}->{parsed.message_id}"
                            )
                        current.qualities[quality.quality] = parsed
                    else:
                        current.diagnostics.append(
                            f"duplicate_quality_ignored:{quality.quality}:{parsed.message_id}"
                        )
                    current.noise_messages = 0
                elif score >= _AMBIGUOUS_THRESHOLD:
                    current.ambiguous_candidates += 1
                    current.diagnostics.append(
                        f"ambiguous_quality:{quality.message.message_id}:{score}"
                    )
                else:
                    current.diagnostics.append(
                        f"rejected_quality:{quality.message.message_id}:{score}"
                    )
                continue

            if current is None:
                continue

            current.messages_since_poster += 1
            current.noise_messages += 1
            if current.noise_messages > self._max_noise_messages:
                groups.append(_finalize_group(current))
                current = None

        if current is not None:
            groups.append(_finalize_group(current))

        return tuple(groups)


def _detect_poster(message: ArchiveMessage) -> _PosterCandidate | None:
    caption = _bounded_caption(message.caption)
    if message.media_kind is not MediaKind.PHOTO or not caption:
        return None

    fields = _extract_fields(caption)
    title_entry = next(
        ((label, value) for label, value in fields.items() if label in _TITLE_LABELS),
        None,
    )
    if title_entry is None:
        return None

    title_label, raw_title = title_entry
    supporting_count = sum(label in _SUPPORTING_POSTER_FIELDS for label in fields)

    is_legacy = _FOLLOWER_TAG in caption or title_label in _LEGACY_ONLY_TITLE_LABELS
    style = ParserStyle.LEGACY if is_legacy else ParserStyle.MODERN

    if style is ParserStyle.MODERN:
        if supporting_count == 0:
            return None
        confidence = min(99, 88 + min(supporting_count, 5) * 2)
    else:
        if supporting_count == 0 and _FOLLOWER_TAG not in caption:
            return None
        confidence = 88 if _FOLLOWER_TAG in caption else 82

    year = _extract_year_from_fields(fields) or extract_year(raw_title)
    display_title = clean_display_title(raw_title)
    normalized_title = normalize_title(raw_title)
    if not display_title or not normalized_title:
        return None

    return _PosterCandidate(
        message=message,
        raw_title=raw_title.strip(),
        display_title=display_title,
        normalized_title=normalized_title,
        year=year,
        style=style,
        confidence=confidence,
    )


def _detect_quality(message: ArchiveMessage) -> _QualityCandidate | None:
    caption = _bounded_caption(message.caption)
    if message.media_kind not in {MediaKind.VIDEO, MediaKind.DOCUMENT} or not caption:
        return None

    quality = extract_quality(caption)
    if quality is None:
        return None

    fields = _extract_fields(caption)
    labeled_title = next(
        (value for label, value in fields.items() if label in _TITLE_LABELS),
        None,
    )

    raw_title = labeled_title or _extract_freeform_quality_title(caption)
    normalized = normalize_title(raw_title) if raw_title else None
    year = extract_year(raw_title) or extract_year(caption)

    return _QualityCandidate(
        message=message,
        quality=quality,
        raw_title=raw_title,
        normalized_title=normalized or None,
        year=year,
    )


def _bounded_caption(caption: str | None) -> str:
    if not caption:
        return ""
    return caption[:_MAX_PARSED_CAPTION_CHARS]


def _extract_fields(caption: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in caption.splitlines():
        match = _FIELD_RE.match(raw_line)
        if not match:
            continue
        label = match.group(1).strip().lstrip("#").casefold()
        value = match.group(2).strip()
        if label and value and label not in fields:
            fields[label] = value
    return fields


def _extract_year_from_fields(fields: dict[str, str]) -> int | None:
    return extract_year(fields.get("السنة"))


def _extract_freeform_quality_title(caption: str) -> str | None:
    for raw_line in caption.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        field_match = _FIELD_RE.match(line)
        if field_match is not None:
            label = field_match.group(1).strip().lstrip("#").casefold()
            if label not in _TITLE_LABELS:
                continue

        candidate = strip_bot_usernames(remove_quality_token(line))
        candidate = strip_year(candidate).strip(" -–—:：")
        candidate = " ".join(candidate.split())
        if candidate and not candidate.startswith("#"):
            return candidate
    return None


def _score_quality(
    *,
    poster: _PosterCandidate,
    quality: _QualityCandidate,
    distance: int,
) -> int:
    score = 80

    if distance > 1:
        score -= min((distance - 1) * 5, 20)

    if poster.year is not None and quality.year is not None:
        if poster.year == quality.year:
            score += 10
        else:
            score -= 35

    if poster.normalized_title and quality.normalized_title:
        ratio = SequenceMatcher(
            None,
            poster.normalized_title,
            quality.normalized_title,
            autojunk=False,
        ).ratio()
        if ratio >= 0.90:
            score += 10
        elif ratio >= 0.70:
            score += 6
        elif ratio >= 0.50:
            score += 3

    return max(0, min(100, score))


def _finalize_group(builder: _GroupBuilder) -> ParsedMovieGroup:
    qualities = tuple(
        sorted(
            builder.qualities.values(),
            key=lambda item: (_quality_sort_key(item.quality), item.message_id),
        )
    )

    if qualities:
        status = GroupStatus.INDEXED
    elif builder.ambiguous_candidates:
        status = GroupStatus.AMBIGUOUS
    else:
        status = GroupStatus.ORPHAN

    return ParsedMovieGroup(
        poster_message_id=builder.poster.message.message_id,
        raw_poster_caption=builder.poster.message.caption or "",
        raw_title=builder.poster.raw_title,
        display_title=builder.poster.display_title,
        normalized_title=builder.poster.normalized_title,
        year=builder.poster.year,
        parser_style=builder.poster.style,
        status=status,
        poster_confidence=builder.poster.confidence,
        qualities=qualities,
        diagnostics=tuple(builder.diagnostics),
    )


def _quality_sort_key(quality: str) -> int:
    order = {"480p": 480, "720p": 720, "1080p": 1080, "2160p": 2160, "4k": 2161}
    return order.get(quality, 9999)
