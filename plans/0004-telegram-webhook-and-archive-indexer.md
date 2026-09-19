# Plan 0004 — Telegram webhook and durable Archive Channel indexer

**Status:** Completed  
**Created:** 2026-09-20  
**Last updated:** 2026-09-20

## Objective

Wire CineGate to Telegram through a secure FastAPI webhook and persist real Archive Channel posts into PostgreSQL using the parser implemented in Plan 0003.

This phase must remain fast under duplicate/rapid webhook deliveries, avoid unnecessary infrastructure, and make all archive writes idempotent.

## Context

Plan 0003 completed:

- Python/aiogram/FastAPI foundation
- PostgreSQL/SQLAlchemy/Alembic foundation
- pure modern + legacy archive parser
- CI with PostgreSQL migration verification

The next missing piece is transport + persistence.

Official Telegram webhook behavior relevant to this plan:

- Telegram retries non-2xx webhook deliveries.
- `secret_token` is delivered in `X-Telegram-Bot-Api-Secret-Token`.
- webhook connections may be concurrent.
- aiogram can be integrated with a non-aiohttp framework by parsing `Update` and using `Dispatcher.feed_update`.

Therefore webhook handling must be duplicate-safe and may not assume “exactly once”.

References reviewed on 2026-09-20:

- https://core.telegram.org/bots/api#setwebhook
- https://docs.aiogram.dev/en/latest/dispatcher/webhook.html

## Scope

### In scope

- application runtime lifecycle for Bot + Dispatcher + Database
- secure FastAPI Telegram webhook endpoint
- constant-time webhook-secret comparison
- aiogram router wiring
- Telegram channel-post → `ArchiveMessage` adapter
- DB-backed runtime settings repository
- configured Archive Channel filtering
- durable movie/quality indexing
- transaction-safe idempotent upserts
- repeated/rapid quality event safety
- parser-result persistence
- owner archive-notification payload generation
- optional owner notification send/edit when `owner_chat_id` is configured
- PostgreSQL integration tests
- webhook transport tests
- startup/shutdown tests where practical
- documentation and two review passes

### Out of scope

- historical UserBot import
- user movie search UX
- rewarded ads
- movie delivery
- auto-delete worker
- full owner settings menu
- production webhook registration CLI/deployment
- automatic detection of deleted Telegram channel messages

## Durable settings

Use `app_settings` for ordinary runtime settings.

Keys needed in this phase:

- `archive_channel_id`
- `owner_chat_id`

These are not secrets and must **not** move into `.env`.

If `archive_channel_id` is absent, Archive Channel updates are ignored safely.

If `owner_chat_id` is absent, indexing still works but owner notifications are skipped.

A later owner/admin plan will expose editing these settings inside Telegram.

## Runtime design

Create one runtime object owning:

- `Bot`
- `Dispatcher`
- `Database`

FastAPI lifespan:

1. load secret settings
2. construct runtime
3. expose runtime through `app.state`
4. on shutdown close Bot HTTP session
5. dispose SQLAlchemy engine

Do not open database connections at import time.

## Webhook security

Endpoint:

`POST /telegram/webhook`

Requirements:

- read `X-Telegram-Bot-Api-Secret-Token`
- compare using `secrets.compare_digest`
- reject missing/wrong token with 403
- validate JSON as aiogram `Update`
- dispatch with `Dispatcher.feed_update`
- return 200 after successful dispatch
- malformed update returns 400
- internal handler failure returns a retryable non-2xx response; do not falsely acknowledge data loss

Bot token must never appear in path/URL/logs.

## Archive message adapter

Map Telegram message types:

- photo → `MediaKind.PHOTO`
- video → `MediaKind.VIDEO`
- document with `video/*` MIME → `MediaKind.DOCUMENT`
- everything else → `MediaKind.OTHER`

Use caption only; media files are not downloaded.

Archive delivery later will use channel/message references.

## Indexing algorithm

### Poster event

For a valid poster:

1. lock/find the latest preceding movie in the same archive channel
2. if the previous movie is still `pending` with zero qualities, finalize it as `orphan`
3. upsert the poster by unique `(archive_channel_id, poster_message_id)`
4. store canonical title/year/style/raw caption/confidence
5. initial status is `pending` until a valid quality exists

Duplicate delivery of the same poster must update safely without creating another movie.

### Quality event

For video/document media:

1. find the latest preceding poster/movie in the same channel
2. reconstruct the poster + incoming quality pair
3. run the existing ArchiveParser validation
4. if accepted:
   - insert/upsert quality
   - uniqueness protects archive message and movie+quality
   - newer message id replaces an older duplicate of the same quality
   - mark movie `indexed`
5. if ambiguous/rejected:
   - do not corrupt existing accepted qualities
   - return a diagnostic result

### Noise

Non-poster/non-quality messages are ignored.

### Last pending poster

A last poster with no quality can remain `pending` until:
- another poster arrives, or
- historical import finalization explicitly closes the batch later

Pending movies are never exposed in user search.

## Concurrency / rapid-event rules

- no in-memory correctness lock
- database unique constraints are authoritative
- mutations for one movie are transactional
- latest movie row is locked while quality replacement/count state is updated
- duplicate Telegram delivery is safe
- duplicate quality of same resolution is deterministic
- network calls to Telegram should not be placed inside long DB transactions
- user-click idempotency is a later phase, but transport design must not prevent it

## Schema changes

Add an index optimized for latest-poster lookup:

- `(archive_channel_id, poster_message_id)` already unique and can serve lookup

Add optional movie field:

- `owner_notification_message_id BIGINT NULL`

Purpose: allow one owner notification per movie to be edited as quality count grows instead of sending noisy duplicates.

No event queue/table is added in this phase unless tests prove direct transactional ingestion is insufficient.

## Owner notification behavior

After the first accepted quality:

- if owner is configured and movie has no notification message id, send:
  `✅ تم حفظ منشورات جديدة\n\n1- <title> (<quality_count>)`
- persist sent notification message id after successful send

After subsequent accepted/newer qualities:

- edit the same owner notification to the new count

Notification failure must **not** roll back successful indexing.

The notifier must be isolated from indexing correctness.

## Tests

### Webhook

- [x] correct secret accepted
- [x] missing secret rejected
- [x] incorrect secret rejected
- [x] malformed JSON/update rejected
- [x] valid update dispatched once

### Adapter

- [x] photo mapping
- [x] video mapping
- [x] video-document mapping
- [x] unrelated document mapping

### Settings repository

- [x] missing setting returns default/None
- [x] set/get int setting
- [x] upsert is idempotent

### Archive indexer integration

- [x] modern poster persists pending
- [x] first quality persists and marks indexed
- [x] multiple qualities attach to same movie
- [x] duplicate webhook delivery does not duplicate movie
- [x] duplicate quality does not duplicate row
- [x] newer same-resolution quality replaces older one deterministically
- [x] old poster with zero qualities becomes orphan when next poster arrives
- [x] cross-language title quality still attaches by sequence
- [x] conflicting year is not persisted as accepted quality
- [x] unconfigured/wrong archive channel is ignored
- [x] quality without poster is ignored

### Quality gates

- [x] Ruff
- [x] pytest
- [x] Alembic PostgreSQL round-trip
- [x] compileall

## Review #1 — correctness

Review:

- lifecycle
- webhook validation
- dispatcher invocation
- transaction boundaries
- SQL conflict handling
- parser reconstruction
- notification error isolation
- all imports/conditions
- test failures/warnings

## Review #2 — critic/performance

Review:

- queries per archive post
- unnecessary abstractions
- locks and transaction duration
- repeated parsing/text work
- whether an event queue is actually needed
- whether any network call is inside DB locks
- duplicate/rapid event behavior
- memory allocations

Do not add Redis/queue infrastructure solely “for scale” without evidence.

## Acceptance criteria

- [x] Telegram webhook endpoint is secure and test-covered
- [x] runtime starts/stops cleanly
- [x] archive channel filter comes from DB runtime settings
- [x] valid archive posters/qualities persist correctly
- [x] duplicate deliveries are idempotent
- [x] notification failure cannot lose indexed content
- [x] CI passes
- [x] both reviews recorded
- [x] docs/memory/status updated
- [x] next exact step documented

## Implementation steps

- [x] 1. Create this plan before code.
- [x] 2. Add settings repository.
- [x] 3. Add archive persistence repository/indexer.
- [x] 4. Add notification-message field migration.
- [x] 5. Add Telegram message adapter.
- [x] 6. Add aiogram archive router.
- [x] 7. Add runtime/lifespan.
- [x] 8. Add secure FastAPI webhook.
- [x] 9. Add integration/unit tests.
- [x] 10. Adjust CI so migrations run before DB integration tests.
- [x] 11. Run full checks.
- [x] 12. Correctness review + fixes.
- [x] 13. Performance/complexity review + fixes.
- [x] 14. Final checks.
- [x] 15. Update repository memory/docs.
- [x] 16. Mark complete.

## Progress notes

### 2026-09-20 — implementation

- Plan created before implementation.
- Official Telegram/aiogram webhook behavior reviewed.
- Added secure FastAPI webhook with constant-time secret comparison.
- Added aiogram runtime lifecycle and archive channel router.
- Added Telegram media adapter without downloading files.
- Added DB-backed runtime settings for `archive_channel_id` and `owner_chat_id`.
- Added transactional, idempotent archive persistence.
- Added owner notification state and same-message quality-count updates.
- Added PostgreSQL migrations 0002 and 0003.
- CI now applies migrations before integration tests and verifies rollback/restore.

### 2026-09-20 — review #1: correctness

Findings and fixes:

- Ruff caught nested async context style issues; corrected before logic review continued.
- Duplicate archive deliveries were explicitly verified against real PostgreSQL constraints.
- Rapid concurrent qualities are serialized per movie with row locking and persist exactly once.
- Rapid duplicate quality deliveries produce one row and one changed result.
- Notification state was initially vulnerable to being lost when Telegram notification failed after successful indexing. Added durable `owner_notification_quality_count` so duplicate webhook retries still know notification work is pending.
- Transient Telegram notification failures now propagate instead of being falsely acknowledged; permanent bad-request/forbidden notification failures are logged without corrupting indexed content.
- Webhook internal handler failures were tested to return non-2xx so Telegram can retry.
- A deterministic concurrent notification race test was added: one older notice is paused while a newer quality arrives, and the final canonical owner message must converge to the latest quality count.

### 2026-09-20 — review #2: performance / complexity

Findings and decisions:

- No Redis, Celery, broker, or external queue was added.
- Archive media is never downloaded by the webhook/indexer.
- Per-message indexing uses short PostgreSQL transactions; Telegram network notification happens only after indexing commits.
- The movie row is locked only while quality/index state mutates, making rapid qualities deterministic without a global application lock.
- Notification convergence is bounded and low-volume.
- Ordinary archive/owner identifiers remain DB settings rather than environment variables.
- Official Bot API documentation states webhook `update_id` can be used to restore sequence if updates arrive out of order and allows 1–100 simultaneous webhook connections.
- CineGate does not yet include a durable global update sequencer. Therefore the **initial production webhook must use `max_connections=1`**. Raising webhook delivery concurrency is forbidden until a dedicated sequencing plan is implemented and tested. This keeps archive sequence semantics safe without prematurely adding a queue.

### 2026-09-20 — final verification

GitHub Actions verified on real PostgreSQL 16:

- Ruff: **all checks passed**
- pytest: **52 passed**
- Alembic: **0001 → 0002 → 0003**, downgrade to base, then upgrade to head: passed
- Python compileall: passed

Two warnings are dependency deprecation notices from FastAPI/Starlette test internals, not CineGate application code.

## Completion summary

Plan 0004 is complete.

CineGate now has a secure webhook transport, DB-backed archive settings, real-time Archive Channel parsing/persistence, duplicate/rapid-event safety, and durable owner notification progress.

**Next exact step:** create Plan 0005 before code for direct English movie search + result buttons + poster copy + available-quality buttons. Search must be typo-tolerant, bounded, secure against hostile input, and efficient without scanning the full catalog in Python.
