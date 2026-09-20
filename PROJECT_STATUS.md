# CineGate Project Status

**Last updated:** 2026-09-20  
**Overall status:** 🟢 Reward/delivery/deletion complete; owner control center next  
**Code status:** Plans 0003–0006 are implemented and CI-verified.

## Completed

- Repository governance/memory system.
- Modern + legacy archive specification/parser.
- Python 3.12 + aiogram 3 + FastAPI foundation.
- PostgreSQL + SQLAlchemy async + asyncpg + Alembic.
- Secure Telegram webhook and durable Archive Channel indexing.
- Duplicate/rapid archive-event safety.
- Durable owner indexing notifications.
- Direct English typo-tolerant movie search.
- PostgreSQL pg_trgm canonical + quality-title alias search.
- Durable per-user search state and stale callback protection.
- Archive poster/info copy and real quality buttons.
- Back navigation and styled Telegram buttons.
- Reward session bound to exact user/movie/quality.
- Telegram-signed Mini App identity validation.
- AdsGram Reward Mini App + server callback integration.
- Dual client/provider reward verification.
- Duplicate/conflicting reward-prompt protection.
- Reward persistence across delivery failures and ad-session expiry.
- Exact Archive Channel quality copy.
- Dynamic delivery caption variables.
- Persistent delivery/delete deadline.
- Durable deletion worker with retry/backoff.
- Periodic stale-state reconciliation.
- Multi-worker deletion safety via `SKIP LOCKED`.
- Honest permanent deletion failure state after Telegram's deletion window.
- Security/operations invariants in `docs/SECURITY.md`.

## Verification

Latest full code verification before documentation-only closeout:

- Ruff: passed
- pytest: **137 passed**
- PostgreSQL 16 migrations `0001 → 0008`: passed
- full downgrade to base + restore to head: passed
- Python compileall: passed

Two warnings are dependency deprecation notices from FastAPI/Starlette internals, not CineGate code.

## Current user flow

Implemented:

`type title → results → movie poster/info → choose quality → reward Mini App → verified reward → quality copied from archive → durable timed deletion`

Production AdsGram credentials/Block ID/public URL are intentionally not hard-coded and can be configured later.

## Next exact step

Create and implement `plans/0007-owner-control-center.md`.

The owner/admin control center must make routine runtime configuration possible inside Telegram without editing source files or restarting CineGate.

Primary scope:

1. owner-only authorization
2. main settings dashboard
3. message/template editor
4. deletion duration
5. search result limit + similarity threshold
6. Archive Channel ID / owner notification chat
7. public Mini App URL + AdsGram Block ID
8. reward/session timing
9. safe validation + preview/reset
10. diagnostics for ambiguous/orphan archive groups and `delete_failed` deliveries
11. audit trail for owner changes
12. current Telegram formatting/styled button support
13. tests and two review passes

## Operational safety rules

- Production webhook registration remains `max_connections=1` until durable global sequencing exists.
- Production access logging must not expose the secret-bearing AdsGram Reward URL.
- Telegram only allows deleting messages sent less than 48 hours ago; CineGate records `delete_failed` rather than pretending success if that window is lost.

## Open decisions

- [ ] production AdsGram Block ID/platform/public URL
- [ ] UserBot library for one-time historical import
- [ ] production hosting/deployment topology
- [ ] exact owner Rich Message editor feature set
- [ ] real-time archive edit/delete reconciliation
- [ ] global webhook sequencer before concurrency > 1

## Active plan

`plans/0006-reward-delivery-and-deletion.md` — **Completed**

## Blockers

None for owner/admin control-center implementation.

Live AdsGram production testing requires the real Block ID/platform configuration, but the owner panel can be built first.

## Resume instruction

Read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, `docs/SECURITY.md`, and Plans 0002–0006 before starting Plan 0007.
