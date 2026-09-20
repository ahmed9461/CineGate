from __future__ import annotations

from cinegate.admin.registry import get_template_definition
from cinegate.db.session import Database
from cinegate.presentation.templates import (
    RenderedTemplate,
    TemplateRenderError,
    render_template,
)
from cinegate.repositories.templates import MessageTemplateRepository


class TemplateService:
    """Render owner-editable Telegram templates with safe defaults."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def render(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> RenderedTemplate:
        definition = get_template_definition(key)
        replacements = replacements or {}

        async with self._database.session() as session:
            stored = await MessageTemplateRepository(session).get(key)

        body = stored.body if stored is not None else definition.default_body
        entities = stored.entities if stored is not None else None

        try:
            return render_template(
                body=body,
                stored_entities=entities,
                allowed_variables=definition.allowed_variables,
                replacements=replacements,
                max_length=definition.max_length,
            )
        except TemplateRenderError:
            return render_template(
                body=definition.default_body,
                stored_entities=None,
                allowed_variables=definition.allowed_variables,
                replacements=replacements,
                max_length=definition.max_length,
            )
