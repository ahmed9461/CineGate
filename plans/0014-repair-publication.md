# Plan 0014 - Reward and Archive repair publication

Status: Implementation complete; exact-commit validation and merge tracked in the pull request
Created: 2026-10-18

## Objective / context / authorization
Publish the owner-approved Plan0011 reward/Archive repairs against main1a7def963df18706a91649c09b69b78856c65204, together with focused Bash-test portability, through a draft PR and same-commit Linux validation. Owner authorized merging after review and successful checks. No production deployment is authorized.

## Scope / dependencies / assumptions
Preserve earned unavailable requests and original proofs/bindings, prevent Archive context/edit/replay corruption, add migrations0011/0012 and regression coverage. Retain actual permission checks and failure cleanup in backup tests; invoke Bash explicitly and preserve LF. Python3.12, PostgreSQL16, Node for the Mini App regression, Bash for operations tests. No unrelated audit fixes, provider activity, credential copying or infrastructure/policy changes.

## Design / schema / security
See Plan0011 and docs/PLAN0011_REPAIR_NOTES.md. Migrations preserve retained-credit history and refuse unsafe0011 downgrade. Archive snapshots cannot recreate old ignored history, and multi-row corrections can require a second replay. Branch contains only approved source/tests/migrations and portable documentation. Local environment files, database data, downloaded binaries and machine-specific evidence are excluded.

## Failure / recovery
CI/network failures remain visible and block merge. Review new upstream changes before updating branch, then rerun checks on exact final head. Never bypass branch rules, force push or discard user work. Rollback rules follow repair notes; clean CI downgrade success does not certify populated production rollback. Windows Git Bash cannot certify POSIX permissions through stat/chmod alone; do not replace security assertions with emulated success.

## Validation / acceptance
- Approved patch hash/preflight checked before application; source review and secret/device-data diff scan before push.
- Historical repaired PostgreSQL suite321 passed in prior isolated validation; current native Windows suite320 passed/3 failed/0 skipped of323. Four original platform failures resolved; remaining output-private-mode and two added644-passfile rejection tests expose Git Bash permission emulation. No skips/weakening introduced.
- Require current Linux PR CI to pass Ruff, complete323-test suite including Node, PostgreSQL migrations and rollback/restore, compilation and Bash syntax. Record exact SHA and results in PR; do not infer from older green runs.
- Review same-head diff/checks before ready/merge. Verify merged commit is on origin/main and post-merge CI succeeds. Preserve local uncommitted setup independently.

## Documentation
Source-of-truth behavior and rollback notes retained in memory/status/decisions/spec/repair notes. Latest validation and merge evidence belong in the PR and GitHub checks; no claim of live Telegram/AdsGram or production readiness. Separate delivery/recovery lock ordering, generic Mini App retries, readiness transport handling, trigram-index metadata and2160p parsing issues remain out of scope.
