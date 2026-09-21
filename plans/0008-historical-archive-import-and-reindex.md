# Plan 0008 — Historical archive import and reindex

**Status:** Completed  
**Created:** 2026-09-20  
**Last updated:** 2026-09-21

## Objective

Implement the one-time historical migration from the owner's original private movie channel into the dedicated CineGate Archive Channel, with durable resume/reconciliation and sequential reindexing.

The importer must preserve Telegram-side media, avoid downloading/re-uploading movie files, survive interruption without blindly duplicating previously forwarded posts, and remain separate from the long-running CineGate service.

## Library decision

Use **Telethon 1.45.x** as an importer-only optional dependency.

Verified before implementation:

- latest stable release checked on 2026-09-20: 1.45.0
- supports async history iteration
- supports forwarding multiple messages
- supports oldest→newest iteration via reverse ordering
- supports normal Telegram UserBot sessions

Do not add Telethon to the normal runtime dependency set.

## Security / authorization boundary

- Owner must use content they are authorized to migrate/distribute.
- UserBot session files are secrets.
- Telegram API hash is secret bootstrap configuration.
- Session files must remain outside Git.
- Importer must never log session contents/API hash/login codes/2FA password.
- Source-channel forwarding protection must be disabled by an authorized owner before import.
- CineGate does **not** toggle, evade, or bypass Telegram content protection.
- If Telegram reports forwarding restriction, importer pauses safely with an actionable error.
- UserBot is not a permanent service; it is invoked only for auth/import/reindex/status commands.

## Runtime separation

Historical import runs through a CLI module:

`python -m cinegate.importer <command>`

Planned commands:

- `auth` — interactive first-time UserBot authorization and session creation
- `run` — resume/start source→archive historical transfer, then reindex
- `transfer` — transfer only
- `reindex` — replay mapped archive messages through CineGate indexing
- `status` — print durable import job status
- `verify` — verify mapping/archive references without changing Telegram

The normal FastAPI/aiogram process does not create a Telethon client.

## Import configuration

### Secrets / bootstrap

Environment:

- `CINEGATE_TELEGRAM_API_ID`
- `CINEGATE_TELEGRAM_API_HASH`
- existing `CINEGATE_DATABASE_URL`

CLI:

- `--session` path, default under ignored `sessions/`

### DB runtime settings

Add owner-editable:

- `source_channel_id`

Reuse:

- `archive_channel_id`
- `owner_chat_id`

Source and archive must be different Telegram channels.

## Import snapshot semantics

At job creation/start:

1. Resolve source and archive entities.
2. Verify source != archive.
3. Check source protection before any transfer.
4. Record the source high-watermark message ID.
5. Record the archive high-watermark message ID existing before import.
6. Import only source messages up to the recorded source high watermark.

This creates a finite historical snapshot and prevents the importer from chasing newly published posts forever.

New posts after the high watermark follow normal owner→Archive publishing/webhook flow.

## Transfer semantics

- Iterate source oldest → newest.
- Skip Telegram service/empty messages that cannot be forwarded.
- Preserve ordinary text/media/noise posts so sequence semantics remain faithful.
- Use Telegram-side forwarding; do not download files.
- Keep forward metadata in the private Archive Channel so source message IDs can be reconciled after a crash.
- User-facing delivery still uses Bot API `copyMessage`, so archive forward attribution is not a user-facing requirement.
- Forward in bounded batches.
- Verify returned destination message IDs are monotonic.
- Persist source→archive message mapping after successful forward.
- Update job checkpoint only after mapping is committed.

Default batch size:

- 25 messages
- configurable CLI range: 1..100

## Crash reconciliation

Telegram forwarding and PostgreSQL commit are separate systems.

Critical crash window:

1. Telegram forwards a batch successfully
2. process crashes before mapping rows are committed

To prevent blind duplicates after restart:

- before forwarding new work, scan Archive messages after the job's archive baseline / last known mapped destination ID
- identify forwarded messages originating from the configured source channel
- use forward metadata to recover original source message IDs
- insert missing mappings idempotently
- advance the source checkpoint only through a contiguous mapped source sequence that has actually been observed

Do not assume exactly-once Telegram forwarding.

## Persistence

Migration 0010 adds:

### archive_import_jobs

- id UUID PK
- source_channel_id
- archive_channel_id
- status:
  - ready
  - running
  - paused
  - transferred
  - reindexing
  - completed
  - failed
- source_high_watermark_id
- archive_baseline_message_id
- last_copied_source_message_id
- last_reindexed_source_message_id
- source_total_estimate
- processed_messages
- copied_messages
- reconciled_messages
- skipped_messages
- reindexed_messages
- missing_archive_messages
- started_at
- updated_at
- completed_at
- last_error
- owner_progress_message_id nullable
- unique source_channel_id + archive_channel_id

### archive_import_message_map

- job_id FK
- source_message_id
- archive_message_id
- copied_at
- reindexed_at nullable
- unique job_id + source_message_id
- unique job_id + archive_message_id

No Telegram media bytes are stored.

## Concurrency

- one durable import job per source/archive pair
- importer acquires PostgreSQL advisory lock for the pair
- concurrent second importer exits instead of racing
- live webhook may continue running
- Archive indexing remains idempotent
- per-movie owner indexing notifications are suppressed while a historical import for that Archive Channel is actively transferring/reindexing
- final bulk summary replaces per-film spam

## FloodWait / Telegram failures

Telethon may auto-sleep for modest FloodWait values.

Importer policy:

- configured automatic wait limit: 600 seconds
- FloodWait <= limit → wait and continue
- FloodWait > limit → mark job paused and exit cleanly
- forwarding restriction → mark paused, explain protection must be disabled
- write/access permission failure → fail/stop with actionable status
- connection interruptions → reconnect/retry bounded by Telethon and continue from durable mapping/checkpoint

No infinite retries.

## Reindex

After transfer reaches the source high watermark:

1. job becomes `transferred`
2. iterate mapping by source message ID ascending
3. fetch mapped Archive messages in bounded batches
4. adapt each Telethon Archive message to CineGate `ArchiveMessage`
5. call existing `ArchiveIndexService.ingest` sequentially
6. update `reindexed_at` + checkpoint after successful ingest
7. missing Archive message → record missing count and continue safely
8. at end, mark job `completed`

Reindex must remain idempotent and resumable.

A `--full` reindex option may replay all mapped messages from the start.

## Progress reporting

CLI always prints periodic progress.

If bot token + owner_chat_id are available:

- send one owner progress message
- edit it at a bounded interval (not per message)
- show:
  - processed / estimated total
  - copied
  - reconciled
  - skipped
  - reindexed
  - missing
  - current phase
- final summary is sent/edited once

During bulk import, suppress normal per-film “saved posts” notifications.

## Owner panel additions

Archive section adds:

- source_channel_id

Diagnostics/status should surface:

- active import status
- source/archive IDs
- copied/reindexed counters
- last error
- final completion summary

Secrets/session paths are not exposed.

## Performance rules

- never download movie files
- never materialize full history in memory
- source history is consumed incrementally
- forwarding batch is bounded
- mapping writes are batched
- archive reindex fetches bounded ID batches
- DB checkpoints update incrementally
- no Redis/Celery/broker
- no permanent UserBot daemon

## Tests

### Configuration / auth boundary

- [x] importer config requires API ID/hash pair
- [x] default session path is ignored by Git
- [x] unauthorized session refuses `run`
- [x] source/archive equality rejected
- [x] forwarding-protected source rejected before transfer

### Job persistence

- [x] create/reuse source+archive job
- [x] source/archive high watermarks stored once
- [x] one concurrent importer wins advisory lock
- [x] status transitions valid
- [x] checkpoints survive service recreation

### Transfer

- [x] source processed oldest→newest
- [x] bounded batch size
- [x] service messages skipped safely
- [x] successful batch maps source→archive IDs
- [x] repeated mapped source messages are not forwarded again
- [x] destination IDs must be monotonic
- [x] Telegram media is never downloaded
- [x] large fake history stays bounded to configured batch

### Crash reconciliation

- [x] simulated forward-before-DB-crash is recovered from archive forward metadata
- [x] recovered map prevents duplicate forward
- [x] unrelated archive forwards are ignored
- [x] duplicate reconciliation is idempotent

### FloodWait / failures

- [x] short FloodWait waits/resumes
- [x] excessive FloodWait pauses job
- [x] forwarding restriction pauses with actionable error
- [x] write-permission failure does not advance checkpoint

### Reindex

- [x] mapped archive messages replay in source order
- [x] resume from last reindexed checkpoint
- [x] full replay is idempotent
- [x] missing destination message increments diagnostic
- [x] existing live-indexed rows do not duplicate
- [x] final status only completes after reindex finishes

### Notification suppression/progress

- [x] historical active job suppresses per-film owner notification
- [x] normal archive notification resumes after import
- [x] progress updates are rate/batch bounded
- [x] final summary contains transfer + reindex totals

### Quality gates

- [x] Ruff
- [x] pytest
- [x] migration apply / downgrade / restore
- [x] compileall
- [x] importer optional dependency installs in CI

## Review #1 — correctness/security

Inspect:

- UserBot session secrecy
- source protection handling
- crash window
- mapping/checkpoint transaction order
- source/Archive forward metadata validation
- no content-protection bypass
- no media download
- high-watermark correctness
- duplicate mapping/forwarding behavior
- reindex order and idempotency
- notification suppression lifecycle

## Review #2 — performance/complexity

Inspect:

- memory bounded by batch
- history iterator streaming
- DB queries per batch
- reindex fetch batch size
- no duplicate full-history scans when checkpoint is valid
- no unnecessary Telegram calls
- FloodWait behavior
- progress update frequency
- no permanent UserBot/service coupling

## Acceptance criteria

- [x] Telethon is importer-only optional dependency
- [x] interactive auth creates ignored session file
- [x] historical transfer can stop/restart without blind duplication
- [x] importer never downloads movie media
- [x] protected source is refused, not bypassed
- [x] durable source→archive mapping exists
- [x] crash reconciliation works
- [x] sequential reindex completes/resumes
- [x] per-film notification spam is suppressed during bulk import
- [x] progress/final summary available
- [x] large-history test demonstrates bounded batching
- [x] full CI passes
- [x] both reviews documented
- [x] memory/status/roadmap/progress updated

## Implementation steps

- [x] 1. Create this plan before code.
- [x] 2. Add Telethon importer optional dependency + CI install.
- [x] 3. Add importer secrets/bootstrap config.
- [x] 4. Add source_channel_id owner setting.
- [x] 5. Add import job/message-map models + migration.
- [x] 6. Implement import repository/state machine.
- [x] 7. Implement Telethon adapter/auth boundary.
- [x] 8. Implement source history iterator + bounded forwarding.
- [x] 9. Implement crash reconciliation from forward metadata.
- [x] 10. Implement bulk-notification suppression.
- [x] 11. Implement sequential mapped-message reindex.
- [x] 12. Implement progress/final summary reporter.
- [x] 13. Implement CLI commands.
- [x] 14. Add importer/admin diagnostics integration.
- [x] 15. Add unit/integration tests.
- [x] 16. Run CI.
- [x] 17. Correctness/security review.
- [x] 18. Performance/complexity review.
- [x] 19. Final CI.
- [x] 20. Update docs/memory/status/roadmap.
- [x] 21. Mark complete.

## Progress notes

### 2026-09-20 — planning and implementation

- Plan created before implementation.
- Telethon 1.45.0 verified as latest stable release.
- Telethon added only as an optional importer dependency.
- Added migration `0010` with durable import jobs and source→archive mappings.
- Implemented CLI commands:
  - `auth`
  - `run`
  - `transfer`
  - `reindex`
  - `status`
  - `verify`
- Implemented historical snapshot high-watermark semantics.
- Implemented oldest→newest bounded Telegram-side forwarding.
- Implemented crash reconciliation from Archive forward metadata.
- Implemented PostgreSQL advisory locking per source/archive pair.
- Implemented bounded FloodWait handling and safe protection/permission failures.
- Implemented sequential resumable reindex through the existing Archive indexer.
- Implemented owner progress reporting with one rate-limited Telegram message.
- Added owner diagnostics/status for latest historical import.
- Added durable suppression for historical per-film owner notifications, including late mapped webhook deliveries after import completion.

### 2026-09-21 — review #1: correctness/security

Findings and fixes:

- Source forwarding protection is refused; no bypass/toggle path exists.
- Protected Archive Channel is also rejected before transfer because later Bot API delivery requires copyable media.
- UserBot session/API hash/login-code/2FA material stays outside logs/repository.
- `MessageEmpty` and service messages are skipped safely.
- Source high-watermark is frozen once so newly published posts are not chased by the historical snapshot.
- Source and destination message IDs are required to be strictly ordered where mapping depends on order.
- Telegram-forward-success / DB-commit crash window is reconciled from durable forward metadata before retry.
- Mapping writes and checkpoints are idempotent.
- Invalid import status transitions are rejected.
- `transfer` is rejected while reindex is active.
- Paused/failed reindex can resume only after transfer checkpoint reached the source high-watermark.
- `run` validates that the selected Archive matches CineGate runtime configuration before transfer starts.
- `verify` is read-only and detects missing/mismatched Archive mappings.
- Progress/reporting failure is isolated from core transfer correctness.
- Historical mapped messages remain notification-suppressed even if their webhook arrives after Job completion.
- No `download_media` usage exists in the repository.

### 2026-09-21 — review #2: performance/complexity

Confirmed/fixed:

- UserBot is a separate CLI process; no permanent daemon is added.
- Source history streams incrementally; the full history is never materialized in memory.
- Default forward batch is 25 and bounded to 100.
- Reindex mapping fetch is bounded.
- Large-history tests verify batch bounds.
- Dialog/entity cache is populated once per Telethon session instead of per channel lookup.
- CLI output is rate-limited.
- Owner Telegram progress attempts are rate-limited even when configuration/network calls fail.
- Progress uses one Telegram message rather than per-message spam.
- DB mapping/checkpoint writes are incremental.
- PostgreSQL advisory locking prevents duplicate import workers without Redis/Celery/broker.
- Bulk notification suppression expires if a running/reindexing job loses its heartbeat.
- No extra media storage or file I/O path was introduced.

### 2026-09-21 — final verification

Latest full GitHub Actions verification on `main`:

- Ruff: **all checks passed**
- pytest: **230 passed**
- PostgreSQL migrations: **0001 → 0010 passed**
- full downgrade to base + restore to head: **passed**
- Python compileall: **passed**
- optional Telethon importer dependency installed in CI

Two warnings remain dependency deprecation notices from FastAPI/Starlette internals, not CineGate code.

### External-live validation note

The importer implementation is complete and fully exercised through deterministic integration/fake-Telegram tests. A real historical Telegram migration has **not** been executed in CI because it requires the owner's Telegram API credentials, authenticated UserBot session, channel access, and temporary source protection change. That live operational validation belongs to launch/deployment work and must use authorized channels only.

## Completion summary

Plan 0008 is complete.

CineGate now has a separate, resumable, bounded one-time historical importer with durable source→Archive mapping, crash reconciliation, sequential reindex, CLI/status/verification tools, progress reporting, owner diagnostics, and explicit content-protection/security boundaries.

**Next exact step:** create Plan 0009 for launch hardening: application-level abuse/rate limits, structured/redacted logging, backup/restore, deployment/runbook, health/readiness, webhook registration discipline, real-time Archive edit/delete reconciliation, and controlled live Telegram validation.
