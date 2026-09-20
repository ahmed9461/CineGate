from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from cinegate.admin.registry import get_template_definition
from cinegate.db.session import Database
from cinegate.presentation.templates import (
    RenderedTemplate,
    TemplateRenderError,
    render_template,
)
from cinegate.repositories.templates import MessageTemplateRepository, StoredTemplate


class TemplateService:
    """Render owner-editable Telegram templates with safe defaults."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def render(
        self,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> RenderedTemplate:
        async with self._database.session() as session:
            return await self.render_with_session(
                session,
                key=key,
                replacements=replacements,
            )

    async def render_with_session(
        self,
        session: AsyncSession,
        *,
        key: str,
        replacements: dict[str, str] | None = None,
    ) -> RenderedTemplate:
        definition = get_template_definition(key)
        stored = await MessageTemplateRepository(session).get(key)
        return _render_record(
            stored=stored,
            default_body=definition.default_body,
            allowed_variables=definition.allowed_variables,
            replacements=replacements or {},
            max_length=definition.max_length,
        )


def _render_record(
    *,
    stored: StoredTemplate | None,
    default_body: str,
    allowed_variables: frozenset[str],
    replacements: dict[str, str],
    max_length: int,
) -> RenderedTemplate:
    body = stored.body if stored is not None else default_body
    entities = stored.entities if stored is not None else None

    try:
        return render_template(
            body=body,
            stored_entities=entities,
            allowed_variables=allowed_variables,
            replacements=replacements,
            max_length=max_length,
        )
    except TemplateRenderError:
        return render_template(
            body=default_body,
            stored_entities=None,
            allowed_variables=allowed_variables,
            replacements=replacements,
            max_length=max_length,
        )
