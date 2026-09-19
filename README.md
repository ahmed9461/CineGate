# CineGate

CineGate is a Telegram movie-search and rewarded-delivery project backed by a private Telegram Archive Channel.

## Current phase

The application foundation, archive parser, secure Telegram webhook, and real-time Archive Channel indexer are implemented.

Current stack:

- Python 3.12
- aiogram 3
- FastAPI
- PostgreSQL
- SQLAlchemy 2 async + asyncpg
- Alembic
- pytest + Ruff

The project intentionally does **not** include Redis, Celery, Kafka, or a microservice split at this stage. Additional infrastructure should only be added when a measured requirement justifies it.

## Current implemented foundation

- modern + legacy archive parsing
- sequence-first poster/quality grouping
- title normalization and typo-safe parser helpers
- orphan/ambiguous group handling
- deterministic duplicate-quality handling
- initial PostgreSQL schema and migrations
- persistent app-settings/message-template tables
- async SQLAlchemy session foundation
- FastAPI health endpoint
- secure Telegram webhook secret validation
- aiogram runtime and Archive Channel router
- real-time idempotent movie/quality persistence
- DB-backed archive/owner runtime settings
- durable owner archive notifications
- rapid duplicate/concurrent quality safety
- local PostgreSQL Compose service
- CI for lint, tests, PostgreSQL migration round-trip, and Python compile checks

User search/movie-page UX, rewarded ads, movie delivery, deletion, owner control center, and historical UserBot import are later phases.

> **Webhook ordering:** Until a durable global update sequencer is added, production webhook registration must use `max_connections=1`.

## Local development

Requirements:

- Python 3.12+
- Docker / Docker Compose

Create a local environment file:

```bash
cp .env.example .env
```

Fill only the local secrets/placeholders in `.env`.

Start PostgreSQL:

```bash
export CINEGATE_POSTGRES_PASSWORD='choose-a-local-password'
docker compose up -d postgres
```

Install the project:

```bash
python -m pip install -e ".[dev]"
```

Apply migrations:

```bash
alembic upgrade head
```

Run the HTTP app:

```bash
uvicorn cinegate.main:app --host 127.0.0.1 --port 8000
```

Health endpoint:

```text
GET /healthz
```

Quality checks:

```bash
ruff check .
pytest -q
python -m compileall -q src tests
```

## Mandatory project workflow

Before doing any work, read:

1. `AGENTS.md`
2. `PROJECT_MEMORY.md`
3. `PROJECT_STATUS.md`
4. `docs/PRODUCT_SPEC.md`
5. `ROADMAP.md`
6. The latest relevant file under `plans/`

Every new feature, fix, refactor, migration, deployment change, or investigation must start with a plan file under `plans/` before implementation.

After meaningful work, update the active plan, project memory, project status, progress log, and any affected decisions/specification.

## Repository memory system

- `AGENTS.md` — mandatory operating rules for any coding agent.
- `PROJECT_MEMORY.md` — durable project memory and confirmed requirements.
- `PROJECT_STATUS.md` — current checkpoint, next step, blockers, and remaining work.
- `ROADMAP.md` — phased project roadmap.
- `docs/PRODUCT_SPEC.md` — current product specification.
- `docs/DECISIONS.md` — decisions and rationale.
- `docs/PROGRESS_LOG.md` — chronological record of completed work.
- `plans/` — one written plan per task/phase before implementation.

## Principle

**Do not rely on chat history as the only source of truth. The repository must always contain enough context to resume CineGate safely from the last checkpoint.**
