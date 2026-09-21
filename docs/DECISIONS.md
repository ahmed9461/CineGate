# CineGate Decision Log

Record durable decisions here. If a decision changes, do not silently delete the old one; mark it superseded and add the new decision.

## D-001 — Archive Channel is the media source of truth

**Status:** Accepted  
**Date:** 2026-09-19

CineGate will use a dedicated private Telegram Archive Channel as the source for movie poster/info posts and quality files.

**Reason:** The owner already has the required content in Telegram and does not need external movie metadata services for normal operation.

---

## D-002 — No external movie lookup for normal search/display

**Status:** Accepted  
**Date:** 2026-09-19

Poster, information, and available qualities come from the archive/index. Search is against the local CineGate catalog.

---

## D-003 — Search is direct English text with typo tolerance

**Status:** Accepted  
**Date:** 2026-09-19

Users type the English movie name directly. No dedicated search button is required. Reasonable misspellings should yield the closest relevant candidates.

---

## D-004 — Runtime settings in persistent storage; environment for secrets

**Status:** Accepted  
**Date:** 2026-09-19

Routine configuration and user-facing message templates should be editable from the owner bot and persist without requiring source edits. Environment configuration is reserved for secrets/sensitive bootstrap values.

---

## D-005 — Movie delivery expiration is durable

**Status:** Accepted  
**Date:** 2026-09-19

Auto-deletion may not depend only on an in-memory timer. Delivery/deletion deadlines are persisted and reconciled after restart.

---

## D-006 — Poster is not deleted by movie-file expiration

**Status:** Accepted  
**Date:** 2026-09-19

Only the delivered quality/file message is subject to the configured timer.

---

## D-007 — One-time UserBot import; ongoing archive submission by owner

**Status:** Accepted  
**Date:** 2026-09-19

For historical migration, owner may temporarily disable forwarding restriction and use a UserBot to populate the Archive Channel. For future additions, owner sends content to the Archive Channel and CineGate indexes it.

---

## D-008 — Reward verification precedes delivery

**Status:** Accepted  
**Date:** 2026-09-19

Selecting a quality creates a reward session. The movie is delivered only after verified rewarded-ad completion.

---

## D-009 — Plan-first repository workflow is mandatory

**Status:** Accepted  
**Date:** 2026-09-19

Every new feature/fix/refactor/migration/integration/investigation starts with a plan file. Important progress must be written back to repository memory/status/logs.

---

## D-010 — Telegram formatting is a first-class requirement

**Status:** Accepted  
**Date:** 2026-09-19

CineGate should deliberately preserve/use Telegram formatting, rich-message capabilities where appropriate, RTL, and supported button styling rather than reducing everything to plain text.

---

## D-011 — Archive grouping is sequence-first

**Status:** Accepted  
**Date:** 2026-09-19

A valid poster opens a movie group. Subsequent quality media are associated primarily by archive message sequence until a new poster boundary or stream end, subject to safety checks.

Exact literal title equality is not required.

Title normalization, year agreement, quality extraction, and textual similarity are supporting confidence signals.

**Reason:** Real archive examples contain harmless caption differences such as `&` vs `and`, punctuation differences, spelling/format variation, and occasional poster/video title language differences.

---

## D-012 — Modern and legacy archive formats are both supported

**Status:** Accepted  
**Date:** 2026-09-19

The current structured format is the primary parser path. Historical legacy posts remain supported for the one-time import and old archive compatibility.

Legacy support includes optional `#طلب_المتابعين` and title-label variants `فيلم`, `فلم`, `الفيلم`, and `الفلم`.

---

## D-013 — Orphan and ambiguous groups are excluded from search

**Status:** Accepted  
**Date:** 2026-09-19

A poster with no accepted following quality media does not become searchable. Unsafe/contradictory associations are marked ambiguous instead of being force-linked.

**Reason:** A missed item is safer than delivering the wrong movie/quality.

---

## D-014 — Python async single-codebase stack

**Status:** Accepted  
**Date:** 2026-09-20

CineGate uses Python 3.12 with aiogram 3 for Telegram and FastAPI/Uvicorn for HTTP surfaces. Business logic is separated into internal modules but remains one deployable application unless measured scaling needs justify a split.

**Reason:** This keeps the system small and testable while matching the asynchronous Telegram/PostgreSQL workload.

---

## D-015 — PostgreSQL is the persistent database

**Status:** Accepted  
**Date:** 2026-09-20

CineGate uses PostgreSQL with SQLAlchemy 2 async, asyncpg, and Alembic migrations.

Database uniqueness constraints and transactions are part of the idempotency strategy for duplicate/rapid Telegram events.

---

## D-016 — Do not add infrastructure without evidence

**Status:** Accepted  
**Date:** 2026-09-20

Redis, Celery, Kafka/RabbitMQ, and a microservice split are not part of the current architecture.

They may be added later only if a concrete load, durability, or coordination requirement cannot be handled cleanly by the existing application + PostgreSQL design.

---

## D-017 — Archive parser consumes ordered messages in one pass

**Status:** Accepted  
**Date:** 2026-09-20

The parser requires ascending Telegram message IDs and processes them in O(n) grouping time without sorting/copying the entire input. Out-of-order input fails explicitly.

**Reason:** Archive retrieval already has an ordering contract; re-sorting every import batch would add unnecessary memory and CPU work and could hide caller bugs.

---

## D-018 — Initial webhook delivery concurrency stays at one

**Status:** Accepted  
**Date:** 2026-09-20

Initial production webhook registration must use `max_connections=1`.

Telegram documents that `update_id` can be used to restore webhook update order if updates arrive out of order, and supports multiple simultaneous webhook connections. CineGate's archive grouping is sequence-sensitive and does not yet have a durable global update sequencer.

**Reason:** Preserve deterministic archive ordering without prematurely adding a queue. Webhook delivery concurrency may only be raised after a dedicated sequencing implementation is planned and tested.

---

## D-019 — Archive indexing commits before owner notification

**Status:** Accepted  
**Date:** 2026-09-20

Archive persistence is the authoritative operation. Telegram owner notification is best-effort after the database transaction commits.

The database stores how many qualities the owner notification has successfully reflected. Duplicate webhook delivery can therefore retry an incomplete notification without duplicating movie/quality records.

**Reason:** A Telegram notification outage must never roll back or lose successfully indexed archive content.

---

## D-020 — PostgreSQL pg_trgm is the movie search engine

**Status:** Accepted  
**Date:** 2026-09-20

CineGate uses bounded PostgreSQL trigram KNN search rather than scanning the catalog in Python or adding a separate search service.

Both canonical poster titles and normalized titles extracted from quality captions are indexed. Quality-caption titles act as local aliases when the poster and video use different languages/names.

**Reason:** It keeps typo-tolerant search fast, local, and consistent with the archive-only content source.

---

## D-021 — One durable current search session per user

**Status:** Accepted  
**Date:** 2026-09-20

Each Telegram user has at most one `user_search_sessions` row. A new search replaces its nonce/results/state.

Movie and Back callbacks must match the current nonce and stored result IDs. Temporary states prevent rapid double-clicks from producing duplicate poster/result UI.

**Reason:** Provides stale-callback and rapid-click safety without an unbounded session-history table or external cache.

---

## D-022 — Year-only movie titles must remain titles

**Status:** Accepted  
**Date:** 2026-09-20

A four-digit title such as `1917` is not automatically stripped as release metadata. A trailing year is treated as release metadata only when meaningful title content remains.

---

## D-023 — AdsGram is the initial rewarded-ad integration

**Status:** Accepted  
**Date:** 2026-09-20

CineGate currently integrates AdsGram Reward for the first production ad path.

The durable reward state machine is kept separate from the AdsGram SDK/web page, but CineGate does **not** introduce a generic multi-provider interface until a second provider is actually needed.

**Reason:** Avoid unnecessary abstraction while preserving a clean boundary for future replacement.

---

## D-024 — Production reward requires dual proof

**Status:** Accepted  
**Date:** 2026-09-20

A reward is not granted from Mini App JavaScript alone.

Production reward requires:

1. Telegram-signed Mini App client completion
2. AdsGram Reward URL server confirmation

The two signals are idempotent and may arrive in either order.

Because AdsGram's documented Reward URL identifies only Telegram `userId`, CineGate allows one active reward session per user. A provider-only confirmation does not skip the current ad.

---

## D-025 — Earned rewards outlive ad-session expiry

**Status:** Accepted  
**Date:** 2026-09-20

The session TTL applies only while waiting for the reward proof.

Once a reward reaches `rewarded`, it remains deliverable even if the original ad-session expiry timestamp passes.

Telegram delivery failure must return the request to `rewarded`; the user must not watch another ad for the same earned reward.

---

## D-026 — Delivery deletion is durable but bounded by Telegram's 48-hour limit

**Status:** Accepted  
**Date:** 2026-09-20

CineGate persists delete deadlines and retries transient failures with a durable worker.

Telegram's Bot API only permits deleting messages sent less than 48 hours ago. If an outage or permanent Telegram error makes deletion impossible, CineGate records `delete_failed` rather than falsely marking the message deleted.

---

## D-027 — Deletion worker uses PostgreSQL coordination, not a task broker

**Status:** Accepted  
**Date:** 2026-09-20

Due deletions are claimed in bounded batches using `FOR UPDATE SKIP LOCKED`. Stale `sending` and `deleting` states are reconciled periodically.

Redis/Celery/message brokers remain unnecessary for the current workload.

---

## D-028 — Owner identity is bootstrap configuration

**Status:** Accepted  
**Date:** 2026-09-20

The authorized owner Telegram user ID is supplied through `CINEGATE_OWNER_USER_ID` and is not editable from the owner panel itself.

**Reason:** The control plane must not be able to redefine who controls the control plane.

---

## D-029 — Owner edit state and audit are durable PostgreSQL data

**Status:** Accepted  
**Date:** 2026-09-20

Owner edits use one durable `owner_edit_sessions` row and successful setting/template changes are appended to `admin_audit_log`.

Mutations are serialized per owner with PostgreSQL transaction advisory locking.

**Reason:** Restart-safe edits and idempotent rapid-click behavior do not require Redis or an in-memory FSM.

---

## D-030 — Formatted templates store Telegram entities, not markup source

**Status:** Accepted  
**Date:** 2026-09-20

The owner edits templates by sending normal formatted Telegram messages. CineGate stores the message body plus Telegram entities and safely remaps UTF-16 offsets when variables are replaced.

Raw HTML/Markdown syntax is not required from the owner.

Advanced raw Rich Message JSON authoring is deferred to a dedicated later phase.

---

## D-031 — Telethon 1.45.x is the historical-import client

**Status:** Accepted  
**Date:** 2026-09-20

The one-time historical Archive migration uses Telethon 1.45.x as an **optional importer-only dependency**.

The UserBot importer runs as a separate CLI process and is not part of the long-running bot/web service.

**Reason:** Telethon 1.45.0 is the latest stable v1 release verified during Plan 0008 planning, supports async history iteration/forwarding, and avoids adding a persistent UserBot process to normal operation.

---

## D-032 — Historical import does not bypass content protection

**Status:** Accepted  
**Date:** 2026-09-20

The owner must temporarily disable source-channel forwarding protection before migration.

The importer detects/reports restricted forwarding and stops safely. It does not toggle, evade, or bypass Telegram content protection.

---

## D-033 — Historical import uses durable source→Archive mappings

**Status:** Accepted  
**Date:** 2026-09-21

Historical migration correctness is based on durable PostgreSQL mapping rows between original source message IDs and Archive Channel message IDs.

A source high-watermark freezes the historical snapshot. If Telegram forwards successfully and the importer crashes before the DB commit, the next run reconciles Archive forward metadata before sending anything new.

**Reason:** Telegram forwarding and PostgreSQL commit are separate systems; exactly-once delivery cannot be assumed.

---

## D-034 — UserBot importer is operational tooling, not application runtime

**Status:** Accepted  
**Date:** 2026-09-21

The Telethon UserBot is invoked only through the historical importer CLI and does not run inside the normal FastAPI/aiogram service.

Its session/API hash remain operational secrets and are excluded from Git/logging.

**Reason:** Keeps production service lighter and reduces exposure of the user-account session.

---

## D-035 — Historical notification suppression is mapping-aware

**Status:** Accepted  
**Date:** 2026-09-21

Per-film owner notifications are suppressed while bulk import/reindex is actively running. In addition, any Archive message durably mapped as historical remains suppressed even if its webhook arrives after import completion.

Normal new, unmapped Archive posts continue to notify the owner.

**Reason:** Telegram webhook delivery may be delayed; job status alone is insufficient to distinguish late historical events.

---

## D-036 — In-process rate limiting is abuse protection only

**Status:** Accepted
**Date:** 2026-09-21

Initial launch uses bounded in-process limits for public search messages, callbacks, and reward-claim HTTP requests.

Limiter state may reset on restart and is not shared across processes. Authorization, reward, delivery, idempotency, and all other correctness decisions remain in PostgreSQL-backed state machines.

**Reason:** One launch process needs lightweight abuse resistance, not distributed limiter infrastructure. A shared limiter can be planned if the deployment topology later expands.

---

## D-037 — Archive edits are real-time; deletion detection is operational

**Status:** Accepted
**Date:** 2026-09-21

CineGate reconciles `edited_channel_post` updates through the Bot API webhook. Invalid or conflicting edits make the affected movie unsafe for search; stale duplicates and unrelated valid qualities cannot reactivate it.

Telegram Bot API does not provide channel-message deletion updates. Missing indexed references are therefore detected with the explicit, read-only `archive verify` UserBot audit. The audit is batched and bounded by database high-watermarks captured at its start.

**Reason:** This represents Telegram's observable events honestly without introducing a permanent UserBot daemon or pretending deletion is real-time.

---

## D-038 — Application logs are structured and secret-path safe

**Status:** Accepted
**Date:** 2026-09-21

CineGate emits lightweight structured JSON application/request logs without request bodies or secret headers. The AdsGram bearer path is redacted, including trailing path variants.

Raw Uvicorn access logging is disabled in the production service template, and the HTTPS edge must also avoid retaining the unredacted callback URL.

**Reason:** The Reward URL contains an environment secret in its path, so generic raw access logs are not safe enough for production.

---

## D-039 — Initial production topology remains one application process

**Status:** Accepted
**Date:** 2026-09-21

Initial production uses PostgreSQL plus one CineGate application process behind a trusted HTTPS edge. Readiness checks PostgreSQL and the deletion worker with a bounded timeout, but deliberately does not depend on Telegram or AdsGram availability.

Webhook delivery remains `max_connections=1`. Backups are published atomically in PostgreSQL custom format, and restore tooling validates the archive and restores in one transaction.

**Reason:** This is the smallest topology consistent with current ordering, recovery, secret-handling, and operational requirements.

---

# Pending decisions

- Production AdsGram credentials/platform values
- Hosting/deployment model
- External monitoring/alert destination
- Telegram Bot API/client feature versions for future presentation work
- Durable global webhook sequencer before raising `max_connections` above 1
