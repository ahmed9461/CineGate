# CineGate

CineGate is a Telegram movie-search and rewarded-delivery project backed by a private Telegram Archive Channel.

## Current phase

Plans 0003–0009 are implemented and CI-verified: application foundation, archive indexing/search, rewarded delivery, durable deletion, owner control, historical import, and launch hardening.

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
- owner-only Telegram control center
- DB-backed runtime settings with no restart
- formatted Telegram template editing and preview/reset
- durable admin edit state + audit history
- owner status/diagnostics
- one-time Telethon historical importer CLI
- durable source→Archive import mapping/checkpoints
- crash reconciliation and resumable historical reindex
- owner/CLI historical import progress and verification
- bounded public search/callback/reward abuse protection
- structured JSON logs with secret-path redaction
- database/worker readiness with bounded timeout
- webhook set/status/delete operations pinned to one connection
- real-time Archive edit reconciliation
- read-only batched Archive reference audit
- atomic PostgreSQL backup/restore tooling
- production deployment, systemd, and launch runbooks
- local PostgreSQL Compose service
- CI for lint, 285 tests, PostgreSQL migration round-trip, Python compile, and shell checks

The remaining launch work is environment-specific: choose/configure the production host and HTTPS edge, provide real Telegram/AdsGram values, perform the fresh-database restore drill, run the controlled live checklist, and connect external alerts. Advanced presentation and any future global webhook sequencer remain separate work.

> **Webhook ordering:** Until a durable global update sequencer is added, production webhook registration must use `max_connections=1`.

> **Deletion limit:** Telegram only permits deleting messages sent less than 48 hours ago. CineGate records `delete_failed` instead of claiming success when the platform can no longer delete a message.

Security-sensitive operating rules are documented in `docs/SECURITY.md`.

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

For the one-time historical UserBot importer:

```bash
python -m pip install -e ".[import]"
python -m cinegate.importer --help
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

Readiness endpoint:

```text
GET /readyz
```

Operational commands:

```bash
python -m cinegate.ops webhook set
python -m cinegate.ops webhook status
python -m cinegate.ops archive verify
```

See `docs/DEPLOYMENT.md`, `docs/BACKUP_RESTORE.md`, and `docs/LAUNCH_CHECKLIST.md` before production launch.

Quality checks:

```bash
ruff check .
pytest -q
python -m compileall -q src tests
bash -n scripts/*.sh
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
