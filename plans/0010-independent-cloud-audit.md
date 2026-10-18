# Plan 0010 — Independent cloud audit

Status: Completed (audit only; fixes remain)
Created and updated: 2026-10-15

## Objective and context
Owner requested current repository tests and review on assistant cloud computer. Audited main commit 1a7def963df18706a91649c09b69b78856c65204. Read repository startup documents.

## Scope, assumptions and dependencies
Run existing tests, lint, compilation, shell validation, PostgreSQL migrations/restore, focused state-machine/archive/JS diagnostics. Python3.12, official PostgreSQL16, declared PyPI dependencies. Local disposable UTF8 databases; no production credentials or external Telegram/AdsGram operations. No fixes or upstream writes.

## Design/data/security impact
Audit only; no production schema, application behavior, or authorization changes. Temporary test DBs contain synthetic fixtures. No secrets obtained.

## Failure/recovery tests
Covered duplicate/stale Archive events, edits, reward unavailability, provider timeout, delivery retry, concurrent stale-send recovery, database refusal, reindex identity changes. Real network/integration permissions remain live-launch work.

## Steps and acceptance
- [x] Read startup context and create plan before investigation
- [x] Install declared dependencies and run complete suite
- [x] Run migrations and actual backup/fresh restore
- [x] Perform targeted review and deterministic repros
- [x] Separate code defects from environment limitations
- [x] Record report and checkpoints; no upstream publication

## Results
285 passed, 0 failed/skipped; Ruff, compileall, bash syntax, pip check passed. PostgreSQL0010 full roundtrip passed. Backup/restore and runtime200/unauthenticated403 smoke passed. Eight confirmed findings grouped in audit report, including permanent active reward blockade, Archive association/edit/replay defects, reindex collision, recovery lock inversion, Mini App retry behavior, readiness connection failure. Alembic metadata/index drift separately noted.

## Recovery and changes
Disposable PG processes stopped. Only local audit docs and environment artifacts changed. No application fixes or remote writes. Initial SQL_ASCII and no-gzip build issues corrected before final passing verification.

## Exact next step
Owner reviews findings; authorize focused repair plan before source edits. Prioritize unavailable earned-reward resolution and archive integrity regressions, preserve earned entitlement, unify lock order, fix Mini App retry, then rerun full suite and new regressions. Production live checklist remains separate.
