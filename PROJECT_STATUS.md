# CineGate Project Status

**Last updated:** 2026-09-20  
**Overall status:** 🟢 Application foundation + archive parser complete  
**Code status:** Foundation code is implemented and CI-verified.

## Completed

- Repository governance/memory system.
- Real modern + legacy archive format specification.
- Python 3.12 project foundation.
- aiogram 3 dependency selected for Telegram.
- FastAPI/Uvicorn HTTP foundation.
- PostgreSQL + SQLAlchemy async + asyncpg persistence foundation.
- Alembic initial schema and migration environment.
- Local PostgreSQL Docker Compose.
- Secrets-only environment settings layer.
- `movies`, `movie_qualities`, `app_settings`, and `message_templates` models.
- Sequence-first modern/legacy archive parser.
- Title/year/quality normalization.
- Orphan/ambiguous handling.
- Duplicate quality deterministic handling.
- Streaming O(n) ordered parser input.
- FastAPI `/healthz`.
- CI with Ruff, pytest, PostgreSQL migration round-trip, and compile checks.
- Two explicit review passes: correctness + performance/complexity.
- Plan 0003 completed.

## Verification

Latest completed foundation verification:

- Ruff: passed
- pytest: **31 passed**
- Alembic/PostgreSQL 16: upgrade → downgrade → upgrade passed
- Python compileall: passed

Dependency deprecation warnings observed in the test runner came from installed FastAPI/Starlette test internals, not CineGate code.

## Current checkpoint

The parser and application foundation are ready, but Telegram is not yet wired to:

- receive webhook updates
- ingest Archive Channel posts
- persist parsed movies/qualities in real time
- send owner indexing notifications

No rewarded-ad integration or end-user movie search flow is implemented yet.

## Next exact step

Create `plans/0004-telegram-webhook-and-archive-indexer.md` **before implementation**.

That plan should cover:

1. aiogram dispatcher/bot lifecycle inside FastAPI.
2. Telegram webhook secret validation.
3. channel post conversion into parser/domain messages.
4. durable real-time archive grouping/indexing.
5. transaction-safe/idempotent movie + quality upserts.
6. rapid/duplicate update handling.
7. owner “تم حفظ منشورات جديدة” notification flow.
8. startup/restart recovery.
9. tests for duplicate, concurrent, and restart cases.
10. archive edit/delete behavior decision where needed.

## Open decisions

- [ ] Rewarded-ad provider (integration intentionally postponed until the Mini App phase)
- [ ] UserBot library for one-time historical import
- [ ] Production hosting/deployment topology
- [ ] Exact Telegram rich-message feature/version choices
- [ ] Real-time archive edit/delete reconciliation behavior

## Known non-negotiable requirements

- Archive Channel is the media source of truth.
- No external movie lookup for posters/info/qualities.
- English direct-text search with typo tolerance.
- Reward verification before delivery.
- Temporary delivered movie auto-deletion must be durable.
- Poster/info is not deleted by the movie timer.
- Runtime settings/messages editable inside the owner bot.
- Environment configuration stays limited to secrets/sensitive bootstrap values.
- Telegram formatting/rich presentation must be preserved intentionally.
- Modern + legacy archive formats remain supported.
- Grouping is sequence-first, not exact-title-first.
- Posters with zero accepted qualities are not searchable.
- Ambiguous data is safer than a wrong automatic association.
- Every new work item starts with a plan and ends with repository memory/status/progress updates.
- Avoid unnecessary infrastructure and hot-path work.

## Active plan

`plans/0003-application-foundation-and-parser.md` — **Completed**

## Blockers

None for the next development phase.

## Resume instruction

Read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, `plans/0002-archive-format-and-parser.md`, and `plans/0003-application-foundation-and-parser.md` before starting Plan 0004.
