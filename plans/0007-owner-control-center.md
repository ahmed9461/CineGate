# Plan 0007 — Owner control center

**Status:** In progress
**Created:** 2026-09-20
**Last updated:** 2026-09-20

## Objective

Build an owner-only Telegram control center for runtime settings, message templates, diagnostics, and public integration values. Changes must persist in PostgreSQL and apply without restart.

## Confirmed requirements

- Arabic-first non-technical owner UI.
- Owner-only authorization on every admin message and callback.
- Runtime settings remain DB-backed.
- Sensitive bootstrap configuration is never shown or edited from the panel.
- One durable edit session per owner; no in-memory FSM for correctness.
- Successful mutations are audited.
- Repeated taps/updates must be idempotent.
- Current Telegram styled buttons are used intentionally.
- Owner edits templates by sending formatted Telegram messages rather than writing markup syntax.

## Runtime settings in scope

- movie_delete_seconds
- search_result_limit
- search_similarity_threshold
- archive_channel_id
- owner_chat_id
- public_base_url
- adsgram_block_id
- reward_session_seconds
- miniapp_init_data_max_age_seconds

All validation is centralized in one allowlisted setting registry.

## Template keys in scope

- welcome
- search_results
- search_no_results
- reward_prompt
- delivery_caption
- movie_unavailable
- stale_search
- reward_not_configured
- active_reward_conflict

Template definitions declare allowed variables and output limits. Unknown variables are rejected.

## Persistence

Migration 0009 adds:

- owner_edit_sessions: one pending edit state per owner.
- admin_audit_log: successful setting/template/reset changes.

## Formatting

Store message body plus Telegram entities when available. Implement safe variable replacement with UTF-16 entity offset remapping. Reject entity boundaries that split a variable token. Delivery captions must be able to pass caption entities.

Raw rich-message JSON editing is intentionally out of scope. A later dedicated rich-message authoring phase can use Telegram Bot API 10.3 without exposing technical JSON to the owner.

## Owner UI

Main sections:

- Messages/templates
- Movie deletion
- Search
- Ads/Mini App
- Archive
- Notifications
- Status
- Diagnostics

Prefer editing the current panel message rather than sending a new message for every navigation step.

## Diagnostics

Show concise counts for indexed/orphan/ambiguous movies, qualities, active/rewarded sessions, pending deletion, and delete_failed deliveries. Problem lists must not expose credentials.

## Concurrency and security

- Admin keys are resolved only through registries.
- Mutations are transactionally serialized per owner.
- Same-value changes do not create duplicate audit noise.
- Unauthorized users are silently ignored by admin routes.
- Ordinary user hot paths must not become slower because of the admin panel.

## Tests

- [ ] owner admin access works
- [ ] non-owner admin access is ignored
- [ ] forged non-owner callbacks are ignored
- [ ] setting parsing/bounds are covered
- [ ] HTTPS public URL validation is covered
- [ ] edit state survives service recreation
- [ ] audit and mutation commit atomically
- [ ] same-value updates create no audit noise
- [ ] template variables are validated
- [ ] Telegram entities are stored
- [ ] variable rendering preserves entity offsets
- [ ] reset restores defaults
- [ ] diagnostics counts are correct
- [ ] callback payloads remain within Telegram limits
- [ ] rapid duplicate mutations are safe
- [ ] Ruff passes
- [ ] pytest passes
- [ ] migrations round-trip passes
- [ ] compileall passes

## Implementation steps

- [x] 1. Create this plan before code.
- [ ] 2. Add owner bootstrap authorization setting.
- [ ] 3. Add edit-state/audit models and migration.
- [ ] 4. Implement typed setting registry.
- [ ] 5. Extend setting/template repositories.
- [ ] 6. Implement owner edit/audit service.
- [ ] 7. Implement entity-aware template rendering.
- [ ] 8. Update user-facing template call sites.
- [ ] 9. Implement admin callbacks/keyboards.
- [ ] 10. Implement owner router and navigation.
- [ ] 11. Implement settings edit/reset.
- [ ] 12. Implement template edit/preview/reset.
- [ ] 13. Implement status/diagnostics.
- [ ] 14. Wire owner router before general user router.
- [ ] 15. Add tests and run CI.
- [ ] 16. Correctness/security review.
- [ ] 17. Performance/complexity review.
- [ ] 18. Final CI and documentation updates.

## Completion summary

Pending.