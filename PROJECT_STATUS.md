# CineGate Project Status

**Last updated:** 2026-10-15
**Overall status:** Plan 0011 local reward/Archive fixes validated; not published or deployed
**Code status:** Historical Plans 0003–0009 are CI-verified. Plan 0011 is locally verified against main `1a7def9`; remote CI has not run these unpublished changes.

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

Review the local Plan 0011 patch and repair notes. Publication, merge and deployment require separate owner authorization; none has occurred.

Scoped reward/Archive fixes pass the complete local PostgreSQL suite (321 tests), lint, compilation, shell checks, migration roundtrip and fresh backup/restore smoke. Read `docs/PLAN0011_REPAIR_NOTES.md` before applying migrations, especially the retained-credit downgrade guard.

Separate audit issues remain: delivery/recovery lock inversion, generic Mini App retry handling, readiness transport errors, ORM trigram-index drift, and preexisting 2160p/year parsing. Plan them independently. Real Telegram/AdsGram/HTTPS/production validation remains unperformed.

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

`plans/0011-reward-and-archive-audit-fixes.md` — **Completed locally; unpublished**

## Blockers

No execution blocker remains for the scoped Plan 0011 local fixes. Separate audit findings above remain unresolved.

Production launch execution requires the real host, credentials, authorized channels, public HTTPS endpoint, and AdsGram values.

## Resume instruction

Read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, `docs/SECURITY.md`, Plan 0009, and `docs/LAUNCH_CHECKLIST.md` before production launch work.


## 2026-10-15 — Local independent audit checkpoint (not published)
Audited commit 1a7def9: 285 tests passed with real PostgreSQL16 UTF8; lint/compile/shell/dependency checks, migration roundtrip and fresh backup/restore passed. Targeted review reproduced defects outside suite coverage: earned-reward lockout after unavailable content, Archive boundary/edit/stale replay integrity, full-reindex resolution collision, delivery/recovery lock inversion, Mini App retry state, readiness transport exception handling. Alembic check flags manually created trigram indexes absent from ORM metadata. See local Plan0010. No application fixes or upstream changes. Next: owner review and authorized repair plan; do not infer production readiness from green existing tests.

## 2026-10-18 - Repair publication candidate
Owner authorized publishing the scoped Plan0011 corrections through reviewed GitHub PR, without production deployment. Candidate also contains explicit Bash execution, Git executable-mode checks on Windows, LF checkout attributes, and two real644-passfile rejection regressions. No permission checks are skipped or relaxed. Native Windows complete suite:320 passed/3 failed/0 skipped of323; Git Bash permission emulation prevents restrictive output-mode and passfile-rejection guarantees. Require exact-commit Linux CI validation including all323 tests and Node execution before merge; use current PR/checks as result source. Alembic's two known trigram-index metadata differences and the other separate audit limitations remain unchanged. No machine-specific paths, secrets or runtime artifacts are included. See plans/0014-repair-publication.md.
