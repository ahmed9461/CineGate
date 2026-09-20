# CineGate Project Status

**Last updated:** 2026-09-20  
**Overall status:** 🟢 Owner control center complete; historical archive import next  
**Code status:** Plans 0003–0007 are implemented and CI-verified.

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
- Rewarded AdsGram Mini App path with dual proof.
- Exact-quality Telegram delivery and durable deletion/recovery.
- Honest `delete_failed` state when Telegram can no longer delete.
- Owner-only Telegram control center.
- DB-backed runtime settings with no restart requirement.
- Formatted Telegram template editing with entities preserved.
- Durable owner edit sessions and audit log.
- Owner status/diagnostics for archive/rewards/deletion problems.
- Owner edit messages restricted to private chat.
- Admin callbacks/keys allowlisted and rapid edits serialized.

## Verification

Latest full verification after Plan 0007:

- Ruff: passed
- pytest: **176 passed**
- PostgreSQL 16 migrations `0001 → 0009`: passed
- full downgrade to base + restore to head: passed
- Python compileall: passed

The two warnings are dependency deprecation notices from FastAPI/Starlette internals, not CineGate code.

## Current user flow

Implemented:

`type title → results → movie poster/info → choose quality → reward Mini App → verified reward → quality copied from archive → durable timed deletion`

Owner runtime configuration is available from Telegram without source edits/restart.

## Current owner flow

`/admin → settings/templates/status/diagnostics → edit/preview/reset → PostgreSQL + audit`

Sensitive bootstrap values remain environment-only.

## Next exact step

Create and implement `plans/0008-historical-archive-import-and-reindex.md`.

Primary scope:

1. one-time UserBot historical migration
2. Telethon 1.45.x as importer-only dependency
3. separate CLI process; no long-running UserBot service
4. owner-provided original source channel ID
5. resumable source→Archive Channel transfer
6. durable source→archive message mapping
7. crash reconciliation before retry
8. bounded batches and FloodWait handling
9. bulk-import notification suppression
10. sequential historical reindex using existing archive indexer
11. progress + final summary
12. large-history validation without loading media files
13. session/API credentials never committed
14. owner manually disables source content protection before import; CineGate does not bypass it

## Operational safety rules

- Production webhook registration remains `max_connections=1` until durable global sequencing exists.
- Production access logging must not expose the secret-bearing AdsGram Reward URL.
- UserBot session files are secrets and remain outside Git.
- Historical importer must not download/re-upload movie media.
- Source content protection must be disabled by an authorized owner before transfer; importer does not bypass it.

## Open decisions

- [ ] production AdsGram Block ID/platform/public URL
- [ ] production hosting/deployment topology
- [ ] real-time archive edit/delete reconciliation
- [ ] advanced Rich Message authoring
- [ ] visual owner button-style customization
- [ ] global webhook sequencer before concurrency > 1

## Active plan

`plans/0007-owner-control-center.md` — **Completed**

## Blockers

None for Plan 0008 implementation.

Live historical transfer will later require:
- Telegram API ID/hash
- an authenticated UserBot session
- owner access to both channels
- original-channel forwarding restriction temporarily disabled

## Resume instruction

Read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, `docs/SECURITY.md`, and Plans 0002–0007 before starting Plan 0008.
