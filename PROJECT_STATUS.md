# CineGate Project Status

**Last updated:** 2026-09-20  
**Overall status:** 🟢 Secure webhook + durable Archive Channel indexing complete  
**Code status:** Plans 0003 and 0004 are implemented and CI-verified.

## Completed

- Repository governance/memory system.
- Real modern + legacy archive specification.
- Python 3.12 + aiogram 3 + FastAPI foundation.
- PostgreSQL + SQLAlchemy async + asyncpg + Alembic.
- Modern/legacy sequence-first parser.
- Secure Telegram webhook secret validation.
- aiogram application runtime/lifecycle.
- Archive Channel media adapter without media downloads.
- DB-backed archive/owner runtime settings.
- Transactional poster and quality persistence.
- Duplicate webhook/poster/quality idempotency.
- Rapid concurrent quality handling with per-movie row locking.
- Newer same-resolution replacement.
- Pending/indexed/orphan transitions.
- Durable owner indexing notifications.
- Concurrent owner-notification convergence.
- Non-2xx webhook response on retryable internal failure.
- CI migration apply → tests → downgrade → upgrade → compile.
- Two explicit review passes for Plans 0003 and 0004.

## Verification

Latest Plan 0004 verification:

- Ruff: passed
- pytest: **52 passed**
- PostgreSQL 16 migrations `0001 → 0002 → 0003`: passed
- downgrade to base and restore to head: passed
- Python compileall: passed

Two warnings remain from FastAPI/Starlette dependency deprecations, not CineGate application code.

## Current checkpoint

Archive posts can now flow:

`Telegram webhook → aiogram router → parser → PostgreSQL → owner notification`

End-user movie search and movie-page UI are not implemented yet.

## Next exact step

Create `plans/0005-search-and-movie-page.md` before implementation.

That plan must cover:

1. direct English text search with no search-mode button
2. safe bounded user input
3. exact/prefix ranking before fuzzy matching
4. typo tolerance without scanning the full catalog in Python
5. multiple close results as inline buttons
6. owner-editable no-result/results templates
7. movie selection callback validation
8. deleting/replacing stale search-result UI cleanly
9. copying poster/info from Archive Channel
10. showing only qualities actually present in DB
11. Back navigation
12. rapid/duplicate callback safety
13. centralized Telegram button rendering/styling
14. tests and two review passes

## Operational safety rule

Until CineGate has a durable global update sequencer, production Telegram webhook registration must use:

`max_connections=1`

This preserves sequence-sensitive archive ingestion. Do not raise it casually.

## Open decisions

- [ ] Rewarded-ad provider/integration
- [ ] UserBot library for one-time historical import
- [ ] Production hosting/deployment topology
- [ ] Exact rich-message feature usage
- [ ] Real-time archive edit/delete reconciliation
- [ ] Durable global webhook sequencing before raising webhook concurrency

## Known non-negotiable requirements

- Archive Channel is the media source of truth.
- No external movie lookup for posters/info/qualities.
- English direct-text search with typo tolerance.
- Reward verification before movie delivery.
- Temporary delivered movie auto-deletion must be durable.
- Poster/info is not deleted by movie timer.
- Runtime settings/messages editable inside owner bot.
- Environment remains secrets/bootstrap-sensitive values only.
- Modern + legacy archive formats stay supported.
- Ambiguous data is safer than wrong automatic association.
- Avoid unnecessary infrastructure and hot-path work.
- Every new work item starts with a plan and ends with repository memory/status/progress updates.

## Active plan

`plans/0004-telegram-webhook-and-archive-indexer.md` — **Completed**

## Blockers

None for search/movie-page implementation.

Live Telegram testing later requires real bot/archive IDs and webhook URL, but those are not required to continue code construction.

## Resume instruction

Read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, and Plans 0002–0004 before starting Plan 0005.
