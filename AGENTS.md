# CineGate Agent Rules

These rules are mandatory for any AI agent, coding assistant, or developer working in this repository.

## 1. Required startup protocol

Before making any change, read in this order:

1. `AGENTS.md`
2. `PROJECT_MEMORY.md`
3. `PROJECT_STATUS.md`
4. `docs/PRODUCT_SPEC.md`
5. `ROADMAP.md`
6. `docs/DECISIONS.md`
7. The newest relevant plan in `plans/`
8. The recent entries in `docs/PROGRESS_LOG.md`

Do not begin implementation from assumptions or from chat memory alone.

## 2. Plan before every new piece of work

Before starting any new feature, bug fix, refactor, migration, deployment change, integration, investigation, or substantial configuration change:

1. Create a new file in `plans/` using `plans/TEMPLATE.md`.
2. Give it the next sequential number, for example:
   - `0002-archive-parser.md`
   - `0003-search-engine.md`
3. Document:
   - objective
   - current context
   - scope
   - out of scope
   - assumptions
   - dependencies
   - implementation steps
   - data/schema impact
   - security/privacy impact
   - failure cases
   - tests
   - rollback/recovery approach
   - acceptance criteria
   - documentation that must be updated
4. Only then begin implementation.

If the intended implementation changes while working, update the plan **before** proceeding with the changed direction.

Small details are not exempt if forgetting them could change behavior, data, security, UX, or recovery.

## 3. Continuous progress tracking

After every meaningful implementation checkpoint:

- Update the active plan checklist.
- Add a dated entry to `docs/PROGRESS_LOG.md`.
- Update `PROJECT_STATUS.md` if current state, next step, blockers, or remaining work changed.
- Update `PROJECT_MEMORY.md` when a durable requirement, constraint, behavior, integration detail, or operating rule is learned or changed.
- Update `docs/DECISIONS.md` when an architectural/product decision is made or reversed.
- Update `docs/PRODUCT_SPEC.md` if user-visible behavior changes.

Never end a work session with important progress existing only in chat, terminal output, or memory.

## 4. Incomplete work must be resumable

If work stops before completion, the repository must state:

- what was completed
- what is partially complete
- what failed
- why it failed, if known
- files/components affected
- tests already run and their results
- the **exact next step**
- any temporary workaround or risk still present

Put this checkpoint in the active plan and `PROJECT_STATUS.md`.

## 5. Source-of-truth priority

When documents conflict, resolve them rather than silently choosing one.

Priority:

1. Explicit latest owner requirement
2. `docs/DECISIONS.md`
3. `PROJECT_MEMORY.md`
4. `docs/PRODUCT_SPEC.md`
5. Active plan
6. Existing implementation

When a newer requirement supersedes an older one, update all affected documentation.

## 6. Secrets and runtime configuration

- `.env` is for secrets and bootstrap-only sensitive configuration.
- Normal runtime settings must live in persistent application storage and be editable through the owner/admin bot where applicable.
- Never commit bot tokens, API secrets, Telegram session files, credentials, private keys, or production connection strings.
- Never log secrets.
- Telegram UserBot session material must never be committed.

## 7. Safety of changes

- Do not perform destructive database or repository operations without a written plan and recovery path.
- Do not erase historical project documentation merely to make it look cleaner.
- Prefer migrations over manual production database edits.
- Do not rewrite Git history unless the owner explicitly requests it.
- Preserve backwards compatibility unless a plan explicitly documents the breaking change.

## 8. Testing discipline

Every implementation plan must define tests before implementation.

At minimum consider:

- happy path
- invalid input
- retries/restarts
- duplicate events
- race conditions
- permission failures
- Telegram/API failures
- database failures
- security abuse cases

Do not mark a plan complete until acceptance criteria and required tests are recorded with results.

## 9. CineGate-specific invariants

Do not change these without an explicit owner decision:

- Telegram Archive Channel is the source of truth for movie media.
- No external movie database is required for posters, movie info, or qualities.
- Users search by typing an English movie title directly; no search button is required.
- Search should tolerate reasonable spelling mistakes and return the closest relevant results.
- The delivered movie file is temporary and is deleted from the bot-user chat after the configured duration.
- Poster/movie information messages are not deleted by the movie-file timer.
- Rewarded ad completion must be verified before delivery.
- Message templates and ordinary settings should be editable inside the bot; secrets remain in environment configuration.
- Telegram formatting / rich-message capabilities and modern button styling must be supported deliberately, not stripped accidentally.

## 10. Definition of done for any task

A task is not done until:

- implementation is complete
- tests/results are recorded
- active plan is updated
- progress log is updated
- memory/status/spec/decisions are updated where relevant
- no undocumented temporary state remains
