# CineGate

CineGate is a Telegram-based movie search and delivery project backed by a private Telegram archive channel.

## Current phase

**Foundation / planning.** No application code has been implemented yet.

The repository is intentionally documentation-first so progress is never lost and every implementation step has an explicit plan.

## Mandatory project workflow

Before doing any work, read:

1. `AGENTS.md`
2. `PROJECT_MEMORY.md`
3. `PROJECT_STATUS.md`
4. `docs/PRODUCT_SPEC.md`
5. `ROADMAP.md`
6. The latest relevant file under `plans/`

Every new feature, fix, refactor, migration, deployment change, or investigation must start with a plan file under `plans/` before implementation.

After meaningful work, update the plan, project memory, project status, and progress log before ending the session.

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
