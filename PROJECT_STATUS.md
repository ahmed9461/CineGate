# CineGate Project Status

**Last updated:** 2026-09-21  
**Overall status:** 🟢 Plan 0009 complete; controlled production launch remains
**Code status:** Plans 0003–0009 are implemented and CI-verified.

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
- Owner status/diagnostics.
- One-time historical UserBot importer.
- Telethon importer-only dependency and separate CLI.
- Durable source→Archive import jobs and message mapping.
- Crash reconciliation after Telegram-forward/DB-commit interruption.
- Bounded oldest→newest historical transfer.
- Protected source/Archive preflight checks; no content-protection bypass.
- Bounded FloodWait handling.
- Resumable sequential historical reindex.
- Read-only mapping verification.
- Rate-limited CLI/owner progress reporting.
- Late historical owner-notification suppression by durable mapping.
- Owner diagnostics for latest historical import.
- Bounded public-user search/callback/reward abuse protection.
- Structured JSON logs with secret-path redaction.
- Liveness, database/worker readiness, and bounded readiness timeout.
- Webhook set/status/delete tooling pinned to `max_connections=1`.
- Real-time Archive edit reconciliation.
- Read-only, batched Archive reference integrity audit.
- Atomic PostgreSQL backup/restore scripts and operational runbooks.
- Hardened single-process systemd example and launch checklist.
- Migration `0010`.

## Verification

Latest full GitHub Actions verification for code commit `09e9d3abce58fb9b833b01b408aa0f6e81d6d4df`:

- Ruff: passed
- pytest: **285 passed**
- PostgreSQL 16 migrations `0001 → 0010`: passed
- full downgrade to base + restore to head: passed
- Python compileall: passed
- shell-script syntax checks: passed
- optional Telethon importer dependency installs in CI

The two warnings are dependency deprecation notices from FastAPI/Starlette internals, not CineGate code.

## Current user flow

Implemented:

`type title → results → movie poster/info → choose quality → reward Mini App → verified reward → quality copied from archive → durable timed deletion`

## Current owner/operations flow

- `/admin → settings/templates/status/diagnostics → edit/preview/reset → PostgreSQL + audit`
- `python -m cinegate.importer auth|run|transfer|reindex|status|verify`
- `python -m cinegate.ops webhook set|status|delete`
- `python -m cinegate.ops archive verify`
- `GET /healthz` and `GET /readyz`

## Next exact step

Deploy the verified `main` revision to the chosen production environment and execute `docs/LAUNCH_CHECKLIST.md`.

This includes:

1. provide the production Telegram/AdsGram secrets and non-secret runtime values
2. configure the trusted HTTPS edge with raw secret-path logging disabled
3. run migrations and a fresh non-production restore drill
4. register/verify the webhook with `max_connections=1`
5. perform the controlled Telegram/AdsGram smoke tests
6. configure external monitoring/alert delivery

## Operational safety rules

- Production webhook registration remains `max_connections=1` until durable global sequencing exists.
- Production access logging must not expose the secret-bearing AdsGram Reward URL.
- UserBot session files/API hash are secrets and remain outside Git/logs.
- Historical importer does not bypass Telegram content protection.
- Archive Channel content protection must remain disabled for user delivery.
- Live migration/launch validation must use channels the owner is authorized to operate.
- The in-process rate limiter is abuse protection, never correctness or authorization state.

## Open decisions

- [ ] production AdsGram Block ID/platform/public URL
- [ ] production hosting/deployment topology
- [ ] external monitoring/alert destination
- [ ] advanced Rich Message authoring
- [ ] visual owner button-style customization
- [ ] global webhook sequencer before concurrency > 1

## Active plan

`plans/0009-launch-hardening-and-deployment.md` — **Completed**

## Blockers

No code blocker remains for Plan 0009.

Production launch execution requires the real host, credentials, authorized channels, public HTTPS endpoint, and AdsGram values.

## Resume instruction

Read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, `docs/SECURITY.md`, Plan 0009, and `docs/LAUNCH_CHECKLIST.md` before production launch work.
