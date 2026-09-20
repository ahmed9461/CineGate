# Plan 0008 — Historical archive import and reindex

**Status:** In progress  
**Created:** 2026-09-20  
**Last updated:** 2026-09-20

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

- [ ] importer config requires API ID/hash pair
- [ ] default session path is ignored by Git
- [ ] unauthorized session refuses `run`
- [ ] source/archive equality rejected
- [ ] forwarding-protected source rejected before transfer

### Job persistence

- [ ] create/reuse source+archive job
- [ ] source/archive high watermarks stored once
- [ ] one concurrent importer wins advisory lock
- [ ] status transitions valid
- [ ] checkpoints survive service recreation

### Transfer

- [ ] source processed oldest→newest
- [ ] bounded batch size
- [ ] service messages skipped safely
- [ ] successful batch maps source→archive IDs
- [ ] repeated mapped source messages are not forwarded again
- [ ] destination IDs must be monotonic
- [ ] Telegram media is never downloaded
- [ ] large fake history stays bounded to configured batch

### Crash reconciliation

- [ ] simulated forward-before-DB-crash is recovered from archive forward metadata
- [ ] recovered map prevents duplicate forward
- [ ] unrelated archive forwards are ignored
- [ ] duplicate reconciliation is idempotent

### FloodWait / failures

- [ ] short FloodWait waits/resumes
- [ ] excessive FloodWait pauses job
- [ ] forwarding restriction pauses with actionable error
- [ ] write-permission failure does not advance checkpoint

### Reindex

- [ ] mapped archive messages replay in source order
- [ ] resume from last reindexed checkpoint
- [ ] full replay is idempotent
- [ ] missing destination message increments diagnostic
- [ ] existing live-indexed rows do not duplicate
- [ ] final status only completes after reindex finishes

### Notification suppression/progress

- [ ] historical active job suppresses per-film owner notification
- [ ] normal archive notification resumes after import
- [ ] progress updates are rate/batch bounded
- [ ] final summary contains transfer + reindex totals

### Quality gates

- [ ] Ruff
- [ ] pytest
- [ ] migration apply / downgrade / restore
- [ ] compileall
- [ ] importer optional dependency installs in CI

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

- [ ] Telethon is importer-only optional dependency
- [ ] interactive auth creates ignored session file
- [ ] historical transfer can stop/restart without blind duplication
- [ ] importer never downloads movie media
- [ ] protected source is refused, not bypassed
- [ ] durable source→archive mapping exists
- [ ] crash reconciliation works
- [ ] sequential reindex completes/resumes
- [ ] per-film notification spam is suppressed during bulk import
- [ ] progress/final summary available
- [ ] large-history test demonstrates bounded batching
- [ ] full CI passes
- [ ] both reviews documented
- [ ] memory/status/roadmap/progress updated

## Implementation steps

- [x] 1. Create this plan before code.
- [ ] 2. Add Telethon importer optional dependency + CI install.
- [ ] 3. Add importer secrets/bootstrap config.
- [ ] 4. Add source_channel_id owner setting.
- [ ] 5. Add import job/message-map models + migration.
- [ ] 6. Implement import repository/state machine.
- [ ] 7. Implement Telethon adapter/auth boundary.
- [ ] 8. Implement source history iterator + bounded forwarding.
- [ ] 9. Implement crash reconciliation from forward metadata.
- [ ] 10. Implement bulk-notification suppression.
- [ ] 11. Implement sequential mapped-message reindex.
- [ ] 12. Implement progress/final summary reporter.
- [ ] 13. Implement CLI commands.
- [ ] 14. Add importer/admin diagnostics integration.
- [ ] 15. Add unit/integration tests.
- [ ] 16. Run CI.
- [ ] 17. Correctness/security review.
- [ ] 18. Performance/complexity review.
- [ ] 19. Final CI.
- [ ] 20. Update docs/memory/status/roadmap.
- [ ] 21. Mark complete.

## Progress notes

### 2026-09-20

- Plan created before implementation.
- Telethon 1.45.0 verified as latest stable release.
- Importer will remain an optional one-time CLI dependency.
- Source protection bypass is explicitly out of scope.

## Completion summary

Pending.
