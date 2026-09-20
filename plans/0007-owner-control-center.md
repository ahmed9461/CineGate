# Plan 0007 — Owner control center

**Status:** Completed
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

- [x] owner admin access works
- [x] non-owner admin access is ignored
- [x] forged non-owner callbacks are ignored
- [x] setting parsing/bounds are covered
- [x] HTTPS public URL validation is covered
- [x] edit state survives service recreation
- [x] audit and mutation commit atomically
- [x] same-value updates create no audit noise
- [x] template variables are validated
- [x] Telegram entities are stored
- [x] variable rendering preserves entity offsets
- [x] reset restores defaults
- [x] diagnostics counts are correct
- [x] callback payloads remain within Telegram limits
- [x] rapid duplicate mutations are safe
- [x] Ruff passes
- [x] pytest passes
- [x] migrations round-trip passes
- [x] compileall passes

## Implementation steps

- [x] 1. Create this plan before code.
- [x] 2. Add owner bootstrap authorization setting.
- [x] 3. Add edit-state/audit models and migration.
- [x] 4. Implement typed setting registry.
- [x] 5. Extend setting/template repositories.
- [x] 6. Implement owner edit/audit service.
- [x] 7. Implement entity-aware template rendering.
- [x] 8. Update user-facing template call sites.
- [x] 9. Implement admin callbacks/keyboards.
- [x] 10. Implement owner router and navigation.
- [x] 11. Implement settings edit/reset.
- [x] 12. Implement template edit/preview/reset.
- [x] 13. Implement status/diagnostics.
- [x] 14. Wire owner router before general user router.
- [x] 15. Add tests and run CI.
- [x] 16. Correctness/security review.
- [x] 17. Performance/complexity review.
- [x] 18. Final CI and documentation updates.

## Progress notes

### 2026-09-20 — implementation

- Added environment bootstrap owner identity through `CINEGATE_OWNER_USER_ID`.
- Added migration `0009` with durable `owner_edit_sessions` and `admin_audit_log`.
- Added typed allowlisted setting/template registries.
- Added Arabic owner control center with:
  - messages/templates
  - movie deletion
  - search
  - Ads/Mini App
  - archive
  - notifications
  - status
  - diagnostics
- Added Edit / Preview / Reset / Cancel actions.
- Added DB-backed settings with immediate runtime effect and no restart requirement.
- Added recent safe audit metadata to diagnostics.
- Owner router is explicitly wired before the general user router.

### 2026-09-20 — review #1: correctness/security

Findings and fixes:

- Admin authorization is checked on every owner message and callback.
- Forged non-owner callbacks are silently ignored.
- Owner edit input is restricted to the owner's **private chat** so a message written in a group cannot accidentally mutate configuration.
- Admin keys can only resolve through the typed registry; arbitrary callback keys cannot write arbitrary DB settings.
- Edit state is durable rather than in-memory and survives service recreation/restart.
- Mutations and audit entries commit in the same PostgreSQL transaction.
- Same-value updates create no duplicate audit noise.
- Rapid duplicate edit submissions are serialized per owner with a PostgreSQL transaction advisory lock; only one mutation wins.
- Invalid setting/template input leaves the edit session active for correction and performs no mutation/audit.
- Template variables are allowlisted and unknown variables are rejected.
- Telegram entities are stored and remapped across variable replacement using UTF-16 offsets.
- Formatting boundaries that split a variable token are rejected.
- Telegram template length limits are enforced conservatively in UTF-16 units, including emoji.
- Delivery captions now pass `caption_entities` to Telegram, so owner formatting is actually used rather than merely stored.
- Sensitive bootstrap values (bot token, webhook secret, AdsGram callback secret, DB credentials) are not exposed in the owner panel.
- Advanced raw Rich Message JSON authoring remains intentionally out of scope; the owner edits formatted Telegram messages instead.

### 2026-09-20 — review #2: performance/complexity

Confirmed:

- No Redis/FSM/cache service is needed for admin correctness.
- Ordinary non-owner messages hit the owner router only for cheap identity/chat checks; no admin DB lookup occurs for ordinary users.
- One durable edit row exists per owner, not an unbounded edit-history state table.
- Audit history is append-only and changes are infrequent.
- Settings sections use batched DB reads.
- User-facing template rendering uses the existing PostgreSQL template store and applies changes immediately without process restart.
- No extra process/service was added.
- Owner diagnostics use bounded problem/audit lists.

### 2026-09-20 — final verification

GitHub Actions with PostgreSQL 16:

- Ruff: **all checks passed**
- pytest: **176 passed**
- PostgreSQL migrations: **0001 → 0009 passed**
- full downgrade to base and restore to head: **passed**
- Python compileall: **passed**

The two warnings remain dependency deprecation notices from FastAPI/Starlette internals, not CineGate code.

## Completion summary

Plan 0007 is complete.

CineGate now has an owner-only Telegram control center with durable settings, formatted message templates, audit history, and diagnostics. Routine configuration changes apply from PostgreSQL without editing source files or restarting the service.

**Deferred intentionally:** visual button-style customization and advanced Telegram Rich Message authoring remain in the dedicated presentation phase rather than exposing technical JSON or adding hot-path complexity here.

**Next exact step:** create `plans/0008-historical-archive-import-and-reindex.md` before implementing the one-time UserBot historical migration, resumable archive backfill, progress reporting, and large-history validation.