# Plan 0003 — Application foundation and archive parser implementation

**Status:** Completed  
**Created:** 2026-09-20  
**Last updated:** 2026-09-20

## Objective

Build the first production-oriented CineGate code foundation and implement the archive parser defined by Plan 0002.

The implementation must be intentionally small, asynchronous where I/O is involved, easy to test, restart-safe at the persistence boundary, and resistant to duplicate/rapid events without introducing infrastructure that is not yet needed.

## Context

Plans 0001 and 0002 established project governance and the real archive parsing rules. No production application code exists yet.

The owner explicitly requires:

- no unnecessary/heavy code
- every function/import/condition reviewed carefully
- strong behavior under rapid clicks/events and duplicate updates
- two reviews after each meaningful phase: functional correctness and critical performance/complexity review
- progress and project memory updated continuously

## Technology decisions for this phase

### Language/runtime

- Python 3.12

### Telegram

- aiogram 3.x
- production direction: webhook-based update ingestion through FastAPI
- long polling may be added later only as a development convenience, not as a separate architecture

### HTTP/API

- FastAPI + Uvicorn

### Database

- PostgreSQL
- SQLAlchemy 2.x async ORM
- asyncpg driver
- Alembic migrations

### Testing/quality

- pytest
- pytest-asyncio
- Ruff
- Python compile/import smoke tests

### Search

- RapidFuzz is reserved for the later search phase. The archive parser itself will not depend on it.

### Explicitly not added now

- Redis
- Celery
- Kafka/RabbitMQ
- microservices
- background job frameworks

PostgreSQL constraints/transactions and idempotent handlers are sufficient for the current scope. Additional infrastructure requires evidence that it is needed.

## Scope

### In scope

- Python package/project structure
- dependency configuration
- secrets-only environment configuration layer
- async database session foundation
- initial SQLAlchemy models needed for archive indexing/settings/templates
- initial Alembic migration
- pure archive parser domain model
- modern + legacy poster detection
- quality detection
- title normalization
- sequence-first grouping
- confidence and orphan/ambiguous outcomes
- duplicate-quality deterministic handling
- parser tests based on owner-provided examples
- FastAPI health endpoint
- local PostgreSQL Docker Compose
- CI workflow for lint/tests/compile checks
- documentation/status updates

### Out of scope

- rewarded ad provider integration
- Telegram user search UX
- delivery and deletion worker
- owner admin menus
- initial UserBot importer
- production deployment
- full real-time archive indexer persistence
- Telegram edit/delete reconciliation

## Architecture

Use one application codebase, separated by responsibility rather than separate deployable services:

- `cinegate.domain` — pure datatypes/enums
- `cinegate.services` — parser/business logic
- `cinegate.db` — models/session
- `cinegate.web` — FastAPI endpoints
- later: `cinegate.bot` — aiogram routers
- later: `cinegate.workers` — durable deletion/reconciliation loops

Business logic must remain callable without Telegram/network/database so it can be tested cheaply.

## Data/schema impact

Initial tables:

### movies

- bigint primary key
- archive_channel_id
- poster_message_id
- display_title
- normalized_title
- year nullable
- parser_style
- status
- raw_poster_caption
- parser_confidence
- created_at
- updated_at
- unique archive channel + poster message

### movie_qualities

- bigint primary key
- movie_id foreign key
- archive_channel_id
- archive_message_id
- quality
- raw_caption
- extracted_title nullable
- normalized_title nullable
- extracted_year nullable
- parser_confidence
- created_at
- unique archive channel + archive message
- unique movie + quality

### app_settings

- key primary key
- JSON value
- updated_at

### message_templates

- key primary key
- text body
- Telegram entities JSON nullable
- rich-message JSON nullable
- updated_at

The final reward/delivery tables are deferred to their own plans.

## Parser rules to implement

- modern/current format first
- legacy format fallback
- poster opens a group
- following quality media collected until next poster/end
- exact title equality is not required
- normalize `&` and `and` as equivalent
- normalize punctuation and whitespace
- preserve raw values
- a group with no accepted quality is `orphan`
- unsafe-only evidence becomes `ambiguous`
- ungrouped quality media are ignored
- duplicate quality within one group is resolved deterministically to the newest archive message id and recorded in diagnostics
- one conflicting quality must not corrupt otherwise valid qualities

## Concurrency/idempotency rules

Even though the real-time indexer is later, schema and service boundaries must make these possible:

- unique constraints prevent duplicate archive records
- transaction boundaries are explicit
- Telegram callback/update identifiers will never be trusted as single-use without persistence
- no global mutable state for correctness
- parser functions are stateless/pure for the same ordered input
- future rapid-click handling must use idempotency keys/unique constraints rather than sleeps/debouncing alone

## Security / privacy / abuse

- no execution of Telegram/user text
- no shell/eval from captions
- bounded caption processing
- regexes must be simple and non-catastrophic
- secrets never committed or logged
- UserBot session files remain ignored
- database queries use SQLAlchemy parameterization

## Implementation steps

- [x] 1. Write this plan before code.
- [x] 2. Create Python project/dependency configuration.
- [x] 3. Create minimal package structure and secrets configuration.
- [x] 4. Add async database foundation/models.
- [x] 5. Add initial Alembic migration.
- [x] 6. Implement parser domain types and normalization.
- [x] 7. Implement modern/legacy parser state machine.
- [x] 8. Add parser test fixtures/cases from Plan 0002.
- [x] 9. Add FastAPI health endpoint.
- [x] 10. Add local PostgreSQL Compose and non-secret example config.
- [x] 11. Add CI checks.
- [x] 12. Run tests, lint, compile/import smoke checks.
- [x] 13. Functional review #1 and fix all findings.
- [x] 14. Critical performance/complexity review #2 and remove unnecessary complexity.
- [x] 15. Re-run all checks.
- [x] 16. Update memory/status/decisions/progress/roadmap.
- [x] 17. Mark plan complete only if acceptance criteria are met.

## Tests to implement/run

### Parser

- [x] modern poster + one quality
- [x] modern poster + multiple qualities
- [x] legacy poster + quality
- [x] all four legacy title-label variants
- [x] optional `#طلب_المتابعين`
- [x] poster with no quality -> orphan
- [x] quality without poster -> ignored
- [x] `&` vs `and`
- [x] punctuation/colon differences
- [x] cross-language poster/video title with contiguous sequence
- [x] conflicting year quality is not blindly accepted
- [x] duplicate quality deterministically keeps newest
- [x] new poster closes previous group
- [x] unrelated/noise handling
- [x] repeated parsing returns same result

### Foundation

- [x] settings reject missing/invalid secret configuration cleanly
- [x] models import successfully
- [x] FastAPI app imports
- [x] health endpoint returns expected payload
- [x] migration metadata matches model intent at review level

### Quality gates

- [x] `ruff check .`
- [x] `pytest`
- [x] `python -m compileall src tests`
- [x] no committed secret/session artifacts

## Failure/recovery

- parser is pure; re-run is safe
- schema changes are migration-managed
- this phase does not mutate production data
- if a migration design is found incorrect before deployment, add a corrective migration; do not hand-edit production state
- no Git history rewriting

## Review protocol

### Review #1 — correctness

Inspect:

- all branches/conditions
- parser boundary transitions
- regex extraction
- optional/null values
- duplicate handling
- test coverage
- imports and startup behavior

### Review #2 — critic/performance

Inspect:

- unnecessary dependencies
- repeated work in hot paths
- unbounded loops/text processing
- needless database queries
- premature abstractions
- allocations/copies that can be avoided
- whether simpler code gives the same safety

Record findings and fixes in this plan before completion.

## Acceptance criteria

- [x] package installs/imports cleanly
- [x] parser meets Plan 0002 behavior
- [x] all required tests pass
- [x] lint/compile checks pass
- [x] no Redis/task queue/microservice added without need
- [x] database uniqueness supports future idempotent indexing
- [x] no secrets committed
- [x] two reviews completed and recorded
- [x] project documentation updated
- [x] exact next step documented

## Progress notes

### 2026-09-20 — implementation

- Plan created before implementation.
- Selected Python 3.12 + aiogram 3 + FastAPI + PostgreSQL + SQLAlchemy async + Alembic.
- Deliberately did not add Redis, Celery, Kafka/RabbitMQ, or a microservice split.
- Added package/config/database/migration/FastAPI foundations.
- Implemented the sequence-first modern + legacy archive parser.
- Added CI with a real PostgreSQL 16 service.

### 2026-09-20 — review #1: correctness

Findings and fixes:

- Ruff found import/order/unused-import issues; all were corrected.
- Poster year extraction initially had a fallback that could accidentally pick a year from story text; removed that unsafe fallback.
- Database session helper was made an explicit async context manager.
- Caption processing was bounded.
- Modern field labels with leading bullets/hyphens (for example `-الفيلم:`) were added based on the owner's real example.
- Underscores are normalized as title separators.
- The shared `الفيلم` label was disambiguated so a legacy post without `#طلب_المتابعين` is not automatically mislabeled as modern.
- Duplicate quality handling and conflicting-year behavior were covered by tests.

### 2026-09-20 — review #2: performance / complexity

Findings and fixes:

- Removed a full `sorted(...)` copy from the parser hot path.
- Parser now consumes an already ordered iterable in one pass: O(n) time for grouping and no forced full-input copy.
- Out-of-order message input fails explicitly instead of being silently rearranged.
- Kept title similarity local to quality candidates only.
- Kept caption processing bounded and regexes simple.
- No extra task queue/cache/search dependency was added prematurely.
- PostgreSQL uniqueness constraints are used as the foundation for future idempotency rather than in-memory locks/sleeps.

### 2026-09-20 — final verification

GitHub Actions verified:

- Ruff: **all checks passed**
- pytest: **31 passed**
- PostgreSQL/Alembic: **upgrade → downgrade → upgrade passed**
- Python compileall: **passed**
- CI run used PostgreSQL 16

Two warnings were emitted from FastAPI/Starlette test dependencies (deprecation notices inside installed packages), not from CineGate application code.

## Completion summary

Plan 0003 is complete.

Implemented a small production-oriented foundation plus a deterministic archive parser without unnecessary infrastructure.

**Next exact step:** create Plan 0004 before code for Telegram webhook/bootstrap + durable real-time Archive Channel indexing into PostgreSQL. The plan must cover rapid/duplicate channel updates, transaction idempotency, persistence of movie groups/qualities, owner indexing notifications, and safe startup/shutdown.
