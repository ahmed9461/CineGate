# CineGate Progress Log

Chronological record of meaningful project progress. Keep entries concise but sufficient to reconstruct what happened.

---

## 2026-09-19 — Repository foundation

### Added

- `README.md`
- `AGENTS.md`
- `PROJECT_MEMORY.md`
- `PROJECT_STATUS.md`
- `ROADMAP.md`
- `docs/PRODUCT_SPEC.md`
- `docs/DECISIONS.md`
- `docs/PROGRESS_LOG.md`
- `plans/TEMPLATE.md`
- `plans/0001-project-foundation.md`
- `.gitignore`

### Established

- Mandatory plan-before-work process.
- Mandatory project-memory updates after meaningful work.
- Explicit incomplete-work checkpoints.
- Archive-first CineGate product architecture.
- Direct English typo-tolerant search requirement.
- Reward-before-delivery requirement.
- Owner-configurable durable movie auto-deletion.
- Owner-editable runtime settings/messages.
- Secrets/session protection rules.
- Rich Telegram presentation requirement.

### Current stop point

No application code has been implemented.

### Exact next step

Wait for the owner to provide real examples of how poster and quality posts are structured in the existing movie channel. Then create `plans/0002-archive-format-and-parser.md` before designing or coding the parser.


---

## 2026-09-19 — Real archive format documented

### Evidence received

The owner supplied real examples of both current and historical movie-post formats.

### Confirmed

- Modern/current poster format with structured movie fields.
- Modern quality captions with title/year and quality markers such as `#480p`, `#720p`, and `#1080p`.
- Historical/legacy poster format with optional `#طلب_المتابعين`.
- Legacy title-label variants `فيلم`, `فلم`, `الفيلم`, and `الفلم`.
- Real naming differences including `&` vs `and`, punctuation differences, and occasional poster/video language mismatch.
- Poster may have one to four following qualities.
- Poster with no valid following quality must not enter search.

### Added

- `plans/0002-archive-format-and-parser.md`

### Decisions

- Sequence-first grouping is the primary archive-linking mechanism.
- Title normalization/year/similarity are supporting confidence signals.
- Exact literal title equality is not required.
- Unsafe groups are ambiguous rather than force-linked.
- Orphan posters are excluded from searchable indexing.

### Documentation updated

- `PROJECT_MEMORY.md`
- `PROJECT_STATUS.md`
- `docs/DECISIONS.md`
- `docs/PRODUCT_SPEC.md`
- `ROADMAP.md`

### Code status

No production application code was started.

### Exact next step

Create a new plan before implementation that selects the application stack/database, defines schema/service boundaries, and converts Plan 0002 cases into executable parser fixtures/tests.


---

## 2026-09-20 — Application foundation and archive parser implemented

### Plan

- `plans/0003-application-foundation-and-parser.md` — completed

### Implemented

- Python 3.12 package structure
- aiogram 3 dependency for Telegram
- FastAPI/Uvicorn HTTP foundation
- PostgreSQL + SQLAlchemy async + asyncpg
- Alembic migration environment and initial schema
- local PostgreSQL Docker Compose
- secrets-only environment settings layer
- archive domain datatypes
- modern + legacy archive parser
- title/year/quality normalization
- orphan/ambiguous group outcomes
- deterministic duplicate-quality behavior
- app settings and Telegram message-template persistence models
- FastAPI `/healthz`
- GitHub Actions CI

### Correctness review

The first review caught and fixed:

- lint/import issues
- an unsafe poster-year fallback that could read a year from story text
- an imprecise async session helper
- missing support for bulleted field labels such as `-الفيلم:`
- underscore title separators
- ambiguous `الفيلم` modern/legacy classification

### Performance/complexity review

The second review:

- removed full-input sorting/copying from the parser
- changed archive parsing to ordered one-pass O(n) grouping
- added explicit out-of-order input rejection
- kept caption processing bounded
- kept Redis/Celery/message brokers/microservices out of the architecture because no requirement currently justifies them

### Verification

GitHub Actions:

- Ruff: passed
- pytest: **31 passed**
- PostgreSQL 16 + Alembic upgrade → downgrade → upgrade: passed
- compileall: passed

### Current stop point

The application foundation and pure parser are complete. Telegram webhook/archive persistence is not wired yet.

### Exact next step

Create `plans/0004-telegram-webhook-and-archive-indexer.md` before implementing aiogram/FastAPI webhook ingestion and durable real-time Archive Channel indexing.


---

## 2026-09-20 — Secure Telegram webhook and durable archive indexing completed

### Plan

- `plans/0004-telegram-webhook-and-archive-indexer.md` — completed

### Implemented

- secure FastAPI Telegram webhook
- constant-time webhook secret validation
- aiogram runtime/lifecycle
- Archive Channel router and media adapter
- DB runtime settings for archive/owner IDs
- real-time poster/quality persistence
- PostgreSQL transaction/idempotency handling
- rapid concurrent-quality serialization
- deterministic duplicate-resolution replacement
- owner archive notification send/edit flow
- durable owner-notification quality count
- transient notification retry behavior
- deterministic concurrent-notification convergence
- migrations `0002` and `0003`

### Review #1 — correctness

Found and fixed:

- nested async transaction-context style issues
- notification loss after index commit + Telegram failure
- duplicate webhook retry not previously knowing notification remained dirty
- stale notification overwrite race during concurrent quality arrivals
- false webhook acknowledgment risk on internal handler failure

### Review #2 — performance / complexity

Confirmed:

- media files are never downloaded for indexing
- indexing transactions are short
- Telegram owner I/O is outside indexing transaction
- no Redis/Celery/broker was added
- row locks are scoped per movie for rapid quality writes
- owner-notification convergence is bounded

Telegram's official Bot API notes that webhook updates can require ordering restoration with `update_id`. Until a durable global sequencer exists, initial production webhook delivery must use `max_connections=1`.

### Verification

- Ruff: passed
- pytest: **52 passed**
- PostgreSQL 16 migrations 0001→0002→0003: passed
- downgrade to base + upgrade to head: passed
- compileall: passed

### Current stop point

Archive ingestion is implemented. End-user search/movie-page UX is next.

### Exact next step

Create `plans/0005-search-and-movie-page.md` before implementing direct English typo-tolerant search and movie/quality UI.


---

## 2026-09-20 — Direct movie search and movie page completed

### Plan

- `plans/0005-search-and-movie-page.md` — completed

### Implemented

- direct private text search with no search button
- PostgreSQL `pg_trgm` typo-tolerant KNN search
- canonical poster-title and quality-caption alias indexes
- English alias search for cross-language poster/video naming
- release-year-aware ranking
- safe year-only movie titles such as `1917`
- bounded result/candidate counts
- durable one-row-per-user search sessions
- nonce-protected callbacks
- rapid double-click single-winner state transitions
- styled Telegram result/quality buttons
- Archive Channel poster/info copy
- available-quality-only keyboard
- Back navigation
- DB-editable search/no-result message bodies
- cleanup after DB failure following Telegram send/copy

### Correctness review

Found and fixed:

- `1917` could have been stripped as a year instead of retained as the movie title
- English video title needed to become a local alias when poster title is another language
- concurrent first search for the same user needed per-user DB serialization
- stale result message writes after a newer search
- duplicate movie-button clicks
- DB failure after Telegram send/copy leaving orphan UI

### Performance/complexity review

Confirmed:

- no full-catalog Python fuzzy scan
- canonical and alias KNN queries are index-eligible
- candidate pool bounded before application ranking
- one durable session row per user
- no Redis/search service/cache introduced
- poster media never downloaded

### Verification

- Ruff: passed
- pytest: **87 passed**
- migrations 0001→0006: passed
- full downgrade/restore: passed
- compileall: passed
- KNN index-eligibility checks: passed

### Current stop point

Pre-ad user flow is complete. Quality selection is not yet linked to reward/delivery.

### Exact next step

Create `plans/0006-reward-delivery-and-deletion.md` before implementing durable reward sessions, provider-neutral Mini App handoff, archive quality delivery, and timed deletion.
