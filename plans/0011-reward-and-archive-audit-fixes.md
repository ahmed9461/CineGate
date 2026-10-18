# Plan 0011 — Reward and Archive audit fixes

Status: Completed locally; unpublished
Created: 2026-10-15
Updated: 2026-10-15

## Objective and context
Owner approved fixing the stuck earned-reward request, then Archive correctness findings, with regression tests. Baseline main 1a7def963df18706a91649c09b69b78856c65204 has 285 passing tests but audit Plan0010 reproduced issues.

## Scope
Fix findings1–5: preserve earned entitlement while releasing undeliverable request blockade; preserve Archive boundaries, revalidate poster edits, reject stale original replay overwriting edits, reconcile existing IDs during full reindex. Add failing-then-passing deterministic regression tests. No production actions or remote publication. Deadlock, generic Mini App retries, readiness and ORM index drift are separate unless inseparable.

## Assumptions and dependencies
Use Python3.12 and isolated PostgreSQL16 UTF8. Telegram/AdsGram boundaries mocked. No credit substitution or deletion of earned entitlement. Exact original content entitlement survives unavailability and can resume if safely restored.

## Proposed design / data impact
Specify exact new reward terminal/blocked state and schema/index updates before implementation; preserve credit/proof and original binding, exclude blocked entitlement from single active advertising session. Resume only exact safe original content. Persist invalidation/order/boundary information as necessary for archive safety. All migrations reversible without silently discarding entitlement. Reviewer checks cross-state replay, duplicate events and concurrency.

## Security/privacy and failure cases
No real credentials or external messages. Maintain dual proof, exact user/movie/quality binding and safe unavailable-state responses. Cover invalid input, retries/restarts, duplicates, archive edits, missing Telegram source, simultaneous claims and creation, database rollback and replay. Reject unsafe content rather than substitute it.

## Implementation steps
- [x] Read baseline/recheck upstream; plan before implementation
- [x] Reproduce focused regressions on baseline
- [x] Specify and implement earned-entitlement resolution
- [x] Implement archive/reindex safety fixes
- [x] Review changed code independently and test cross-component behavior
- [x] Run full suite, Ruff, compile/shell, migration roundtrip
- [x] Update memory/status/progress and evidence; package local patch

## Tests and acceptance
All new regressions fail on baseline and pass after repair; complete PostgreSQL suite passes without skips. Earned credit preserved; unrelated movie request permitted after permanent unavailability. Restored original quality recoverable without a second ad. Wrong-file associations and stale reactivation blocked; full reindex handles same-ID quality correction. Migrations roundtrip on disposable DB; no production deployment implied.

## Rollback/recovery
All changes local, deliver patch against baseline. Never rewrite upstream or alter production. Restore local baseline only by explicit tracked file-level reversal, preserving audit evidence. New migration downgrade must define treatment of blocked credit and avoid unique-index collisions.

## Documentation updates
Update this plan, PROJECT_MEMORY.md, PROJECT_STATUS.md, docs/PROGRESS_LOG.md; update decisions/spec for new earned-entitlement semantics. Preserve separate unaddressed findings.

## Progress
2026-10-15: Owner approval verified; upstream main unchanged; only preexisting local audit docs modified. Work started.

### Approved implementation design (before code)
- Migration20261015_0011: earned unavailable state/marker retained with original movie/quality-row/resolution binding and both proof timestamps. Exclude preserved unavailable/resumed entitlement from active-ad restriction and provider's user-only callback selection. Delivery returns controlled unavailable response; creation can release unsafe earned active blocker. Safe exact existing binding restoration may resume original entitlement while another ad session exists. Keep existing row-bound duplicate-quality semantics, no new immutable metadata snapshots or mass invalidation of legacy credits. Guard downgrade when unsupported preserved states exist rather than discard credit.
- Migration20261015_0012: durable Archive message snapshots keyed by channel/message, storing media kind, caption and optional edit timestamp. Seed known current metadata. Initial-message duplicates cannot overwrite current snapshot; older timestamped edits rejected. Parse real intervening ordered snapshots in bounded group scope, preserve sequence-first tolerance. Revalidate attached qualities after poster edits without replacing row identity. Full reindex uses explicit reconciliation of current history. Per-channel transactional coordination; preserve movie→quality lock order. Define snapshot lifecycle/cleanup and metadata registration explicitly.

### Archive history-read concurrency refinement
Snapshot0012 additionally stores a monotonic row version. Historical importer captures each version before fetching Telegram history; authoritative same-second reconciliation compares that version under channel lock. A concurrent newer edit wins and stale fetched data cannot overwrite it. This supports equal-second current-history repair while preserving stale-event safety. Add dedicated regression tests. Parse only the affected first group and stop at its boundary, with bounded diagnostic retention rather than rescanning closed noise tails.

## Completion verification
Final complete suite:321 passed, zero failed/skipped, one upstream Starlette deprecation warning. Ruff, compileall, shell syntax, whitespace checks passed. Baseline six reward cases and four original Archive cases failed before repair; additional nine integrated Archive cases also fail on pristine source. Independent scoped review found no remaining correctness/security blocker after bounded conflict-query fix. Legacy reward migration, populated Archive migration, guarded retained-credit downgrade, clean full migration roundtrip, backup/fresh restore and runtime smoke passed. Node unavailable retry test and negative-control mutation verified. No new model drift: alembic check still flags only the two known preexisting trigram-index differences.

Final limitations: same-second conflict remains unavailable until fresh authoritative history; old ignored pre-migration events cannot be reconstructed by schema seeding; simultaneous multi-row quality corrections may need a second full replay but remain safely ambiguous. Separate deadlock/generic Mini App/readiness/index drift/2160p parser findings remain. No upstream write or production integration executed. Deliverable is a local patch against1a7def9 plus reproducible evidence.
