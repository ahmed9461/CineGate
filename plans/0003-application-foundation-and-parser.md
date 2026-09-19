# Plan 0003 — Application foundation and archive parser implementation

**Status:** In progress  
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
- [ ] 2. Create Python project/dependency configuration.
- [ ] 3. Create minimal package structure and secrets configuration.
- [ ] 4. Add async database foundation/models.
- [ ] 5. Add initial Alembic migration.
- [ ] 6. Implement parser domain types and normalization.
- [ ] 7. Implement modern/legacy parser state machine.
- [ ] 8. Add parser test fixtures/cases from Plan 0002.
- [ ] 9. Add FastAPI health endpoint.
- [ ] 10. Add local PostgreSQL Compose and non-secret example config.
- [ ] 11. Add CI checks.
- [ ] 12. Run tests, lint, compile/import smoke checks.
- [ ] 13. Functional review #1 and fix all findings.
- [ ] 14. Critical performance/complexity review #2 and remove unnecessary complexity.
- [ ] 15. Re-run all checks.
- [ ] 16. Update memory/status/decisions/progress/roadmap.
- [ ] 17. Mark plan complete only if acceptance criteria are met.

## Tests to implement/run

### Parser

- [ ] modern poster + one quality
- [ ] modern poster + multiple qualities
- [ ] legacy poster + quality
- [ ] all four legacy title-label variants
- [ ] optional `#طلب_المتابعين`
- [ ] poster with no quality -> orphan
- [ ] quality without poster -> ignored
- [ ] `&` vs `and`
- [ ] punctuation/colon differences
- [ ] cross-language poster/video title with contiguous sequence
- [ ] conflicting year quality is not blindly accepted
- [ ] duplicate quality deterministically keeps newest
- [ ] new poster closes previous group
- [ ] unrelated/noise handling
- [ ] repeated parsing returns same result

### Foundation

- [ ] settings reject missing/invalid secret configuration cleanly
- [ ] models import successfully
- [ ] FastAPI app imports
- [ ] health endpoint returns expected payload
- [ ] migration metadata matches model intent at review level

### Quality gates

- [ ] `ruff check .`
- [ ] `pytest`
- [ ] `python -m compileall src tests`
- [ ] no committed secret/session artifacts

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

- [ ] package installs/imports cleanly
- [ ] parser meets Plan 0002 behavior
- [ ] all required tests pass
- [ ] lint/compile checks pass
- [ ] no Redis/task queue/microservice added without need
- [ ] database uniqueness supports future idempotent indexing
- [ ] no secrets committed
- [ ] two reviews completed and recorded
- [ ] project documentation updated
- [ ] exact next step documented

## Progress notes

### 2026-09-20

- Plan created before implementation.
- Stack selected to balance reliability and simplicity.
- No application code existed before this plan.

## Completion summary

Pending.
