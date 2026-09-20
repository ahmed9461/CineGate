import pytest
from aiogram.enums import MessageEntityType
from aiogram.types import MessageEntity

from cinegate.presentation.templates import (
    TemplateRenderError,
    render_template,
    serialize_entities,
    validate_template_source,
)


def utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def test_variable_replacement_preserves_entity_around_variable() -> None:
    body = "Movie: %movie%!"
    variable_offset = utf16_len("Movie: ")
    entity = MessageEntity(
        type=MessageEntityType.BOLD,
        offset=variable_offset,
        length=utf16_len("%movie%"),
    )

    rendered = render_template(
        body=body,
        stored_entities=serialize_entities([entity]),
        allowed_variables=frozenset({"%movie%"}),
        replacements={"%movie%": "🎬 Interstellar"},
        max_length=4096,
    )

    assert rendered.text == "Movie: 🎬 Interstellar!"
    assert len(rendered.entities) == 1
    assert rendered.entities[0].offset == variable_offset
    assert rendered.entities[0].length == utf16_len("🎬 Interstellar")


def test_entity_after_emoji_replacement_shifts_utf16_offset() -> None:
    body = "%movie% END"
    end_offset = utf16_len("%movie% ")
    entity = MessageEntity(
        type=MessageEntityType.ITALIC,
        offset=end_offset,
        length=utf16_len("END"),
    )

    rendered = render_template(
        body=body,
        stored_entities=serialize_entities([entity]),
        allowed_variables=frozenset({"%movie%"}),
        replacements={"%movie%": "🎬"},
        max_length=4096,
    )

    assert rendered.text == "🎬 END"
    assert rendered.entities[0].offset == utf16_len("🎬 ")


def test_entity_boundary_cannot_split_variable_token() -> None:
    body = "X %movie% Y"
    entity = MessageEntity(
        type=MessageEntityType.BOLD,
        offset=utf16_len("X %"),
        length=utf16_len("movie"),
    )

    with pytest.raises(TemplateRenderError, match="splits variable"):
        validate_template_source(
            body=body,
            stored_entities=serialize_entities([entity]),
            allowed_variables=frozenset({"%movie%"}),
            max_length=4096,
        )


def test_unknown_template_variable_is_rejected() -> None:
    with pytest.raises(TemplateRenderError, match="unsupported"):
        validate_template_source(
            body="Hello %unknown%",
            stored_entities=None,
            allowed_variables=frozenset(),
            max_length=4096,
        )


def test_rendered_length_limit_is_enforced() -> None:
    with pytest.raises(TemplateRenderError, match="exceeds"):
        render_template(
            body="%movie%",
            stored_entities=None,
            allowed_variables=frozenset({"%movie%"}),
            replacements={"%movie%": "x" * 11},
            max_length=10,
        )
