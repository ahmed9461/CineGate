# CineGate Project Status

**Last updated:** 2026-09-20  
**Overall status:** 🟢 Search + movie page complete; reward/delivery next  
**Code status:** Plans 0003–0005 are implemented and CI-verified.

## Completed

- Repository governance/memory system.
- Real modern + legacy archive specification.
- Python 3.12 + aiogram 3 + FastAPI foundation.
- PostgreSQL + SQLAlchemy async + asyncpg + Alembic.
- Sequence-first archive parser.
- Secure Telegram webhook and durable Archive Channel indexing.
- Duplicate/rapid archive-event safety.
- Durable owner indexing notifications.
- Direct English movie search with typo tolerance.
- PostgreSQL pg_trgm KNN indexes.
- Search by canonical poster title and quality-caption aliases.
- Release-year-aware ranking.
- Safe year-only titles such as `1917`.
- Durable single-current search session per Telegram user.
- Stale callback protection with nonce + stored result IDs.
- Rapid double-click single-winner movie opening.
- Archive poster/info copy via Telegram without downloading media.
- Only actually available qualities rendered.
- Back navigation.
- Styled Telegram inline buttons.
- DB-editable search/no-result message bodies.
- Cleanup of orphan UI after post-Telegram DB failures.
- Two review passes through Plan 0005.

## Verification

Latest Plan 0005 verification:

- Ruff: passed
- pytest: **87 passed**
- PostgreSQL 16 migrations `0001 → 0006`: passed
- downgrade to base + restore to head: passed
- Python compileall: passed
- canonical + quality-alias trigram KNN queries verified index-eligible

Two warnings remain from FastAPI/Starlette dependency deprecations, not CineGate application code.

## Current user flow

Implemented today:

`type movie title → search results → select movie → Archive poster/info → quality buttons → Back`

Quality selection is currently validated but not yet connected to the rewarded-ad/delivery state machine.

## Next exact step

Create `plans/0006-reward-delivery-and-deletion.md` **before implementation**.

It must cover:

1. durable reward session bound to user + movie + exact quality
2. provider-neutral Mini App handoff
3. signed/unguessable reward session token
4. verified server-side reward completion state
5. replay/duplicate reward protection
6. preserve rewarded state if Telegram delivery temporarily fails
7. copy selected quality from Archive Channel
8. owner-editable delivery caption with `%movie%`, `%year%`, `%quality%`, `%time%`
9. durable delivery/deletion deadline
10. delete only delivered movie message, never the poster
11. deletion reconciliation after restart
12. rapid quality-click safety
13. AdsGram adapter boundary, while real Block ID/credentials remain deferred
14. tests and two review passes

## Operational safety rule

Until a durable global webhook sequencer exists:

`max_connections=1`

for production Telegram webhook registration.

## Open decisions

- [ ] final rewarded-ad provider credentials/block configuration
- [ ] UserBot library for one-time historical import
- [ ] production hosting/deployment topology
- [ ] exact Rich Message editor/features
- [ ] real-time archive edit/delete reconciliation
- [ ] durable global webhook sequencing before raising webhook concurrency

## Known non-negotiable requirements

- Archive Channel is the media source of truth.
- No external movie lookup for posters/info/qualities.
- Search is direct text, English-focused, typo tolerant.
- Quality requires verified reward before delivery.
- Delivered movie message is temporary and durably auto-deleted.
- Poster/info is never removed by movie expiry.
- Runtime settings/messages live in DB and are owner-editable.
- Environment remains secrets/bootstrap-sensitive values only.
- Modern + legacy archive formats stay supported.
- Ambiguous archive data is safer than wrong association.
- Avoid unnecessary infrastructure/hot-path work.
- Every new work item starts with a plan and ends with memory/status/progress updates.

## Active plan

`plans/0005-search-and-movie-page.md` — **Completed**

## Blockers

None for reward/delivery implementation.

Real AdsGram Block ID/production Mini App values can be added after the internal reward/delivery flow is complete.

## Resume instruction

Read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, and Plans 0002–0005 before starting Plan 0006.
