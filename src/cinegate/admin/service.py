from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from cinegate.admin.registry import (
    AdminValidationError,
    TemplateDefinition,
    get_setting_definition,
    get_template_definition,
)
from cinegate.db.models import (
    AdminAuditLog,
    AppSetting,
    OwnerEditSession,
)
from cinegate.db.session import Database
from cinegate.presentation.templates import validate_template_source
from cinegate.repositories.settings import SettingsRepository
from cinegate.repositories.templates import (
    MessageTemplateRepository,
    StoredTemplate,
)


@dataclass(frozen=True, slots=True)
class EditSessionView:
    owner_user_id: int
    edit_kind: str
    target_key: str


@dataclass(frozen=True, slots=True)
class MutationResult:
    changed: bool
    target_key: str
    value: Any


class OwnerAdminService:
    """Transactional owner settings/templates and durable edit state."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def begin_edit(
        self,
        *,
        owner_user_id: int,
        edit_kind: str,
        target_key: str,
    ) -> EditSessionView:
        _validate_edit_target(edit_kind, target_key)

        async with self._database.session() as session, session.begin():
            await _lock_owner(session, owner_user_id)
            statement = insert(OwnerEditSession).values(
                owner_user_id=owner_user_id,
                edit_kind=edit_kind,
                target_key=target_key,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[OwnerEditSession.owner_user_id],
                set_={
                    "edit_kind": statement.excluded.edit_kind,
                    "target_key": statement.excluded.target_key,
                    "started_at": func.now(),
                    "updated_at": func.now(),
                },
            )
            await session.execute(statement)

        return EditSessionView(owner_user_id, edit_kind, target_key)

    async def get_edit(self, owner_user_id: int) -> EditSessionView | None:
        async with self._database.session() as session:
            row = await session.get(OwnerEditSession, owner_user_id)
            if row is None:
                return None
            return EditSessionView(
                owner_user_id=row.owner_user_id,
                edit_kind=row.edit_kind,
                target_key=row.target_key,
            )

    async def cancel_edit(self, owner_user_id: int) -> bool:
        async with self._database.session() as session, session.begin():
            await _lock_owner(session, owner_user_id)
            row = await session.get(OwnerEditSession, owner_user_id)
            if row is None:
                return False
            await session.delete(row)
            return True

    async def get_setting_effective(self, key: str) -> Any:
        definition = get_setting_definition(key)
        async with self._database.session() as session:
            value = await SettingsRepository(session).get(key)
        return definition.default if value is None else value

    async def get_settings_effective(
        self,
        keys: tuple[str, ...],
    ) -> dict[str, Any]:
        definitions = {
            key: get_setting_definition(key)
            for key in keys
        }
        async with self._database.session() as session:
            stored = await SettingsRepository(session).get_many(keys)
        return {
            key: stored.get(key, definition.default)
            for key, definition in definitions.items()
        }

    async def get_template_effective(self, key: str) -> StoredTemplate:
        definition = get_template_definition(key)
        async with self._database.session() as session:
            stored = await MessageTemplateRepository(session).get(key)
        if stored is not None:
            return stored
        return StoredTemplate(
            key=key,
            body=definition.default_body,
            entities=None,
            rich_message=None,
        )

    async def apply_setting_edit(
        self,
        *,
        owner_user_id: int,
        raw_value: str,
    ) -> MutationResult:
        async with self._database.session() as session, session.begin():
            await _lock_owner(session, owner_user_id)
            edit = await _require_edit_session(
                session,
                owner_user_id=owner_user_id,
                expected_kind="setting",
            )
            definition = get_setting_definition(edit.target_key)
            parsed = definition.parse(raw_value)

            current_row = await session.get(AppSetting, definition.key)
            old_value = (
                definition.default if current_row is None else current_row.value
            )

            changed = parsed != old_value
            if changed:
                await SettingsRepository(session).set(definition.key, parsed)
                _append_audit(
                    session,
                    owner_user_id=owner_user_id,
                    action="set",
                    target_type="setting",
                    target_key=definition.key,
                    old_value=old_value,
                    new_value=parsed,
                )

            await session.delete(edit)

        return MutationResult(changed, definition.key, parsed)

    async def apply_template_edit(
        self,
        *,
        owner_user_id: int,
        body: str,
        entities: list[dict[str, Any]] | None,
    ) -> MutationResult:
        async with self._database.session() as session, session.begin():
            await _lock_owner(session, owner_user_id)
            edit = await _require_edit_session(
                session,
                owner_user_id=owner_user_id,
                expected_kind="template",
            )
            definition = get_template_definition(edit.target_key)
            validate_template_source(
                body=body,
                stored_entities=entities,
                allowed_variables=definition.allowed_variables,
                max_length=definition.max_length,
            )

            repository = MessageTemplateRepository(session)
            current = await repository.get(definition.key)
            old_payload = _template_payload(current, definition)
            new_payload = {"body": body, "entities": entities}

            changed = new_payload != old_payload
            if changed:
                await repository.set(
                    key=definition.key,
                    body=body,
                    entities=entities,
                )
                _append_audit(
                    session,
                    owner_user_id=owner_user_id,
                    action="set",
                    target_type="template",
                    target_key=definition.key,
                    old_value=old_payload,
                    new_value=new_payload,
                )

            await session.delete(edit)

        return MutationResult(changed, definition.key, new_payload)

    async def reset_setting(
        self,
        *,
        owner_user_id: int,
        key: str,
    ) -> MutationResult:
        definition = get_setting_definition(key)

        async with self._database.session() as session, session.begin():
            await _lock_owner(session, owner_user_id)
            row = await session.get(AppSetting, definition.key)
            if row is None:
                return MutationResult(False, definition.key, definition.default)

            old_value = row.value
            await session.delete(row)
            changed = old_value != definition.default
            if changed:
                _append_audit(
                    session,
                    owner_user_id=owner_user_id,
                    action="reset",
                    target_type="setting",
                    target_key=definition.key,
                    old_value=old_value,
                    new_value=definition.default,
                )

        return MutationResult(changed, definition.key, definition.default)

    async def reset_template(
        self,
        *,
        owner_user_id: int,
        key: str,
    ) -> MutationResult:
        definition = get_template_definition(key)

        async with self._database.session() as session, session.begin():
            await _lock_owner(session, owner_user_id)
            repository = MessageTemplateRepository(session)
            current = await repository.get(definition.key)
            if current is None:
                return MutationResult(
                    False,
                    definition.key,
                    _template_payload(None, definition),
                )

            old_payload = _template_payload(current, definition)
            default_payload = _template_payload(None, definition)
            await repository.delete(definition.key)
            changed = old_payload != default_payload
            if changed:
                _append_audit(
                    session,
                    owner_user_id=owner_user_id,
                    action="reset",
                    target_type="template",
                    target_key=definition.key,
                    old_value=old_payload,
                    new_value=default_payload,
                )

        return MutationResult(changed, definition.key, default_payload)


def _validate_edit_target(edit_kind: str, target_key: str) -> None:
    if edit_kind == "setting":
        get_setting_definition(target_key)
        return
    if edit_kind == "template":
        get_template_definition(target_key)
        return
    raise AdminValidationError("نوع التعديل غير معروف.")


async def _require_edit_session(
    session,
    *,
    owner_user_id: int,
    expected_kind: str,
) -> OwnerEditSession:
    edit = await session.scalar(
        select(OwnerEditSession)
        .where(OwnerEditSession.owner_user_id == owner_user_id)
        .with_for_update()
    )
    if edit is None:
        raise AdminValidationError("لا توجد جلسة تعديل نشطة.")
    if edit.edit_kind != expected_kind:
        raise AdminValidationError("جلسة التعديل الحالية من نوع آخر.")
    _validate_edit_target(edit.edit_kind, edit.target_key)
    return edit


def _append_audit(
    session,
    *,
    owner_user_id: int,
    action: str,
    target_type: str,
    target_key: str,
    old_value: Any,
    new_value: Any,
) -> None:
    session.add(
        AdminAuditLog(
            owner_user_id=owner_user_id,
            action=action,
            target_type=target_type,
            target_key=target_key,
            old_value=old_value,
            new_value=new_value,
        )
    )


def _template_payload(
    stored: StoredTemplate | None,
    definition: TemplateDefinition,
) -> dict[str, Any]:
    if stored is None:
        return {"body": definition.default_body, "entities": None}
    return {"body": stored.body, "entities": stored.entities}


async def _lock_owner(session, owner_user_id: int) -> None:
    await session.execute(
        select(func.pg_advisory_xact_lock(owner_user_id))
    )
