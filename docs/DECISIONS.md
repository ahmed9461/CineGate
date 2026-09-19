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

# Pending decisions

- Ad provider
- UserBot implementation library
- Hosting/deployment model
- Telegram Bot API/client feature versions
- Real-time archive edit/delete reconciliation behavior
