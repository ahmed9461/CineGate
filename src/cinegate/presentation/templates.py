from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aiogram.types import MessageEntity

_VARIABLE_RE = re.compile(r"%[a-z_]+%")


class TemplateRenderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RenderedTemplate:
    text: str
    entities: tuple[MessageEntity, ...] = ()


def serialize_entities(
    entities: list[MessageEntity] | tuple[MessageEntity, ...] | None,
) -> list[dict[str, Any]] | None:
    if not entities:
        return None
    return [
        entity.model_dump(mode="json", exclude_none=True)
        for entity in entities
    ]


def render_template(
    *,
    body: str,
    stored_entities: list[dict[str, Any]] | None,
    allowed_variables: frozenset[str],
    replacements: dict[str, str],
    max_length: int,
) -> RenderedTemplate:
    if not body:
        raise TemplateRenderError("template body cannot be empty")
    if max_length <= 0:
        raise ValueError("max_length must be positive")

    variables = tuple(_VARIABLE_RE.finditer(body))
    unknown = {match.group(0) for match in variables} - allowed_variables
    if unknown:
        names = ", ".join(sorted(unknown))
        raise TemplateRenderError(f"unsupported template variables: {names}")

    missing = {
        match.group(0)
        for match in variables
        if match.group(0) not in replacements
    }
    if missing:
        names = ", ".join(sorted(missing))
        raise TemplateRenderError(f"missing template replacements: {names}")

    spans: list[tuple[int, int, int, int, str]] = []
    pieces: list[str] = []
    cursor = 0

    for match in variables:
        variable = match.group(0)
        replacement = replacements[variable]
        pieces.append(body[cursor : match.start()])
        pieces.append(replacement)

        start_u16 = _utf16_len(body[: match.start()])
        end_u16 = _utf16_len(body[: match.end()])
        replacement_u16 = _utf16_len(replacement)
        spans.append(
            (
                start_u16,
                end_u16,
                replacement_u16,
                end_u16 - start_u16,
                variable,
            )
        )
        cursor = match.end()

    pieces.append(body[cursor:])
    rendered = "".join(pieces)

    if _utf16_len(rendered) > max_length:
        raise TemplateRenderError(
            f"rendered template exceeds {max_length} UTF-16 units"
        )

    entity_dicts = _remap_entities(
        body=body,
        entities=stored_entities or [],
        replacement_spans=spans,
    )
    entities = tuple(
        MessageEntity.model_validate(entity)
        for entity in entity_dicts
    )
    return RenderedTemplate(text=rendered, entities=entities)


def validate_template_source(
    *,
    body: str,
    stored_entities: list[dict[str, Any]] | None,
    allowed_variables: frozenset[str],
    max_length: int,
) -> None:
    if not body:
        raise TemplateRenderError("template body cannot be empty")
    if _utf16_len(body) > max_length:
        raise TemplateRenderError(
            f"template source exceeds {max_length} UTF-16 units"
        )

    variables = tuple(_VARIABLE_RE.finditer(body))
    unknown = {match.group(0) for match in variables} - allowed_variables
    if unknown:
        names = ", ".join(sorted(unknown))
        raise TemplateRenderError(f"unsupported template variables: {names}")

    spans = [
        (
            _utf16_len(body[: match.start()]),
            _utf16_len(body[: match.end()]),
            _utf16_len(match.group(0)),
            _utf16_len(match.group(0)),
            match.group(0),
        )
        for match in variables
    ]
    _remap_entities(
        body=body,
        entities=stored_entities or [],
        replacement_spans=spans,
    )


def _remap_entities(
    *,
    body: str,
    entities: list[dict[str, Any]],
    replacement_spans: list[tuple[int, int, int, int, str]],
) -> list[dict[str, Any]]:
    body_u16_length = _utf16_len(body)
    remapped: list[dict[str, Any]] = []

    for raw in entities:
        entity = dict(raw)
        try:
            start = int(entity["offset"])
            length = int(entity["length"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TemplateRenderError("invalid Telegram entity offsets") from exc

        if start < 0 or length <= 0 or start + length > body_u16_length:
            raise TemplateRenderError("Telegram entity is outside template text")

        end = start + length
        new_start = start
        new_end = end

        for span_start, span_end, replacement_len, original_len, variable in (
            replacement_spans
        ):
            if span_start < start < span_end or span_start < end < span_end:
                raise TemplateRenderError(
                    f"formatting boundary splits variable {variable}"
                )

            delta = replacement_len - original_len
            if span_end <= start:
                new_start += delta
                new_end += delta
            elif start <= span_start and span_end <= end:
                new_end += delta

        entity["offset"] = new_start
        entity["length"] = new_end - new_start
        remapped.append(entity)

    return remapped


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2
