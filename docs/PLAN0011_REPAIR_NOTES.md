# Plan 0011 repair and migration notes

Local changes against `1a7def963df18706a91649c09b69b78856c65204`, verified 2026-10-15. The owner subsequently authorized a reviewed GitHub publication; no production deployment is authorized. Current publication/CI state is tracked in the pull request.

## What is repaired

- An earned reward whose original movie/quality-row/resolution is unsafe or whose Telegram source is definitively missing is retained as unavailable. Proof timestamps and original binding survive; another ad request can proceed.
- A safe restoration resumes the same earned request without another ad, even alongside a separate active ad session. Provider callbacks target only the active ad, not retained requests. Transient failures/restarts preserve that separation.
- Claims return actionable HTTP409 for unavailable content. The newly introduced preserved-request UI retries claims without replaying the ad.
- Archive indexing retains ordered message snapshots including noise/boundaries. Poster edits revalidate attached qualities; initial duplicates cannot overwrite reconciled current content. Exact quality-row identity is preserved.
- Full historical replay reconciles existing Archive message IDs rather than inserting a duplicate on resolution edits. Prefetch versions prevent stale history from overwriting a newer event.
- Conflicting content with the same Telegram second-level edit timestamp bumps an observation version and fails closed. It cannot be served until fresh authoritative history safely resolves it. The affected group is bounded by its next poster; parser diagnostics and closed tails are bounded.

## Migrations and rollback

`20261015_0011` adds unavailable reward fields/state and excludes preserved entitlements from the active-ad unique index. Existing reward fields/proofs are not rewritten.

`20261015_0012` stores Archive current snapshots/version/conflict evidence and seeds metadata currently known to the catalog. Invalid known entries remain unsafe. Historical ignored events cannot be reconstructed by the migration; do not assume installing it repairs every old catalog association.

Downgrade0011 deliberately refuses any retained marker, including a subsequently delivered retained request, before discarding fields or recreating the old uniqueness constraint. Do not delete/expire earned credit to force downgrade. Keep the new schema, or follow a separately planned recovery using an appropriate pre-upgrade backup. Clean disposable head→base→head roundtrip is tested; this does not imply every populated production downgrade is permitted.

Downgrading0012 drops snapshot evidence; re-upgrade seeds known metadata again, and authoritative history validation is needed for discarded context. Back up first and review recovery before any real deployment.

## Verification

- Six reward and four Archive/reindex regressions failed on pristine baseline before repair
- Complete local Python/real-PostgreSQL16 UTF8 suite: **321 passed**, zero failures/skips, one dependency deprecation warning
- Ruff, compileall, shell syntax and diff whitespace checks passed
- Legacy reward upgrade and retained-credit downgrade guards verified
- Populated Archive upgrade and clean migrations checked
- Actual script backup→fresh restore, head0012,13 tables; runtime health/readiness200 and unauthenticated webhook403
- Deterministic Node test confirms pending→ad→unavailable→retry makes no second ad or duplicate claim; reinstating the former listener behavior fails this test

Node.js must be available to execute the JavaScript regression; that dedicated test explicitly skips when Node is absent. It ran here without skips. Telegram/AdsGram boundaries are fakes, not live integrations.

## Remaining separate work and limitations

- Existing delivery/recovery inverse-lock-order deadlock
- Generic Mini App retry handling outside the new unavailable path
- Readiness connection-refusal response
- Alembic autogeneration still reports the two preexisting manually created trigram indexes missing from ORM metadata; no new drift found
- Preexisting `#2160p` caption parsing may treat2160 as a release year, making a valid quality ambiguous; reproduced separately, not repaired here
- Multi-row resolution corrections may remain safely ambiguous until a second full replay frees/reconciles all slots. First pass does not force reassignment or serve conflicting content
- Real Telegram channel permissions, live AdsGram proof/delivery/deletion, public HTTPS, alerts and production load remain unverified

Retain single-process launch and webhook `max_connections=1`. No global webhook sequencer is introduced by these fixes.


## Portable validation follow-up
Operations tests invoke real Bash explicitly and preserve LF scripts. Windows checks Git's executable bit because native stat has none. Private-output and passfile checks remain real assertions: Windows Git Bash currently reports mode644 outside a script but600 under umask077 with unchanged Windows ACL. The323-test Windows run has320 passes and3 failures: restrictive output mode plus two added readable-passfile rejection cases. This limitation is intentionally visible; validate all323 tests on Linux in current PR CI. Use a genuine POSIX permission environment for these shell operations; Windows ACL-aware operations require separate work.
