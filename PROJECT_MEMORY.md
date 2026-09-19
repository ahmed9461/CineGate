# CineGate Project Memory

**Last updated:** 2026-09-20  
**Purpose:** Durable source of project context so work can resume without relying on chat history.

---

## 1. Product summary

CineGate is a separate Telegram bot for searching movies and delivering an available quality after the user completes a rewarded advertisement.

The project does **not** need an external movie database for posters, movie metadata, or quality availability. The Telegram archive is the content source.

---

## 2. Confirmed user flow

1. User opens the bot.
2. User directly types the movie name in English.
3. No dedicated “Search” button is required.
4. Bot searches the local movie index.
5. Search should tolerate reasonable English spelling mistakes.
6. If several close results exist, bot shows them as buttons.
7. User selects a movie.
8. Previous result UI may be removed/replaced as appropriate.
9. Bot copies/sends the movie poster + original information from the archive channel.
10. Under the poster, bot shows only qualities actually available for that movie, e.g.:
    - 480p
    - 720p
    - 1080p
    - Back
11. User chooses a quality.
12. Bot explains that one short advertisement must be completed before receiving that quality.
13. “Watch ad” opens a Telegram Mini App / rewarded-ad flow.
14. Delivery is unlocked only after verified ad completion.
15. Bot copies the selected quality from the archive channel to the user.
16. The delivered movie message gets a configurable caption/template.
17. After a configurable duration, the **movie file message** is automatically deleted from the user’s chat with the bot.
18. The poster/information message is not deleted by this timer.

---

## 3. Archive model

### Original channel

- Owner already has a private original movie channel.
- Original channel may have Telegram content-forwarding/saving restriction enabled.
- CineGate must not rely on bypassing Telegram content protection.

### Initial migration

- For the one-time initial import, owner will temporarily disable the original channel’s forwarding restriction.
- A Telegram UserBot may then copy/forward historical movie posts into the dedicated CineGate Archive Channel.
- After initial migration, the protection on the original channel can be re-enabled.

### Archive Channel

- A separate private Telegram channel is used as CineGate’s storage/archive.
- CineGate bot is an administrator in the archive channel as needed.
- Archive Channel is the source of truth for:
  - poster/information post
  - movie quality messages/files
  - Telegram message references required for delivery

### Ongoing updates

After the initial migration:

- Owner will also send new movie content to the Archive Channel.
- CineGate indexes new archive posts automatically.
- Owner receives a summary notification after successful indexing, conceptually:

```
تم حفظ منشورات جديدة

1- Interstellar (3)
```

Meaning the movie was saved with three associated qualities.

If multiple movies are indexed together, notification may summarize all of them.

### Confirmed archive parsing format

The owner supplied real archive examples on 2026-09-19. Two posting styles must be supported.

#### Modern/current style

This is the primary style used now.

Poster/info posts typically contain structured fields such as:

- `الفيلم:`
- `التصنيف:` / `النوع:`
- `البلد:`
- `اللغة:`
- `الترجمة:`
- `السنة:`
- `التقييم:`
- `القصة:`

One or more quality videos follow the poster. Video captions normally contain the movie title plus a resolution marker such as `#480p`, `#720p`, or `#1080p`.

#### Legacy style

Historical posts may contain `#طلب_المتابعين` and any of these title-label variants:

- `فيلم`
- `فلم`
- `الفيلم`
- `الفلم`

The hashtag is helpful but is not mandatory. Quality captions usually contain title + quality + bot username/noise text.

#### Confirmed parser rule

**Sequence is the primary linkage signal.** A valid poster opens a movie group. Following quality media are collected for that group until the next poster boundary or stream end, with confidence/safety checks.

Exact title equality is not required.

The parser must tolerate:

- `&` vs `and`
- punctuation differences such as `:`
- small title spelling/format differences
- poster title and quality-caption title being in different languages
- bot usernames/noise in legacy captions

Title normalization, year matching, and text similarity are supporting signals only.

If a poster has no valid following quality media, it becomes an orphan/ignored-for-search group and must not enter the searchable catalog.

Unsafe groups are marked ambiguous rather than force-linked.

Full specification: `plans/0002-archive-format-and-parser.md`.

---

## 4. Search behavior

Confirmed:

- English movie titles only.
- No Arabic title search requirement.
- User types text directly.
- No required search-mode button.
- Prefer relevant exact/near matches before fuzzy matches.
- Support reasonable spelling mistakes.
- Show multiple close candidates as Telegram buttons.
- No-result message is owner-editable.

Current desired default no-result copy:

```
عذرا لم أجد نتائج بحث ‼️

هذا يعني اما الفيلم غير متوفر في ذاكرتي او ان نص البحث غير دقيق ، حاول كتابة الاسم الصحيح و اذا مازالت تظهر هذه الرسالة ف هذا يعني ان الفيلم غير متوفر.
```

Final wording remains editable from the bot.

Security requirements:

- Treat user search text strictly as data.
- Parameterized database queries.
- No eval/shell execution from user input.
- Input length limits.
- Rate limiting / abuse protection.
- Safe normalization and fuzzy matching.

---

## 5. Rewarded advertisements

- A selected quality requires completion of one rewarded advertisement before delivery.
- Ad provider/network is **not finalized yet**.
- Provider must allow rewarded/incentivized traffic and provide a reliable completion/reward signal suitable for server-side verification.
- Do not unlock delivery merely because the Mini App was opened.
- A reward session must bind at minimum:
  - Telegram user
  - movie
  - selected quality
  - archive message reference
  - reward status
  - timestamps
- One reward must not be reusable to unlock unrelated qualities.
- If reward succeeds but delivery temporarily fails, system should preserve rewarded state so the user is not unfairly forced to watch another ad for the same pending delivery.

---

## 6. Temporary delivery and deletion

Owner can configure movie deletion timing from inside the bot.

Example delivery caption:

```
Top Gun 1986 720p

مهم جدا
يرجى تحويل الفيديو الى رسائل المحفوظة او اي محادثة اخرى لانه سوف يتم حذفه بعد %time%
```

Required template variables include at least:

- `%movie%`
- `%year%`
- `%quality%`
- `%time%`

Additional useful variables may be added after planning, such as `%seconds%` or `%expires_at%`.

Important behavior:

- Changing deletion duration should not require editing the entire message template.
- `%time%` resolves dynamically.
- Only the delivered movie/file message is automatically deleted.
- Poster/info stays.
- Deletion must survive application restart.
- Do not rely only on in-memory sleep timers.
- Persist deletion jobs / delivery expiry data.
- On restart, reconcile overdue or pending deletions.

---

## 7. Owner/admin configuration

Strong requirement: **normal settings must be manageable from inside the bot.**

Examples:

- deletion duration
- message templates
- search result count
- fuzzy-match behavior/thresholds where appropriate
- archive/indexing notifications
- advertisement configuration that is not secret
- enable/disable applicable features
- button presentation/style
- other runtime behavior

Changing normal settings should not require:

- editing source code
- editing `.env`
- restarting the whole project unnecessarily

`.env` is reserved for secrets and sensitive bootstrap configuration.

---

## 8. Editable messages and variables

Bot-facing messages should be stored as editable templates rather than scattered hard-coded strings.

Expected template categories include:

- welcome/start
- search results
- no results
- movie selection
- watch advertisement
- ad failure
- ad success
- delivery caption
- generic error
- archive indexing owner notification

Templates should expose documented variables and validate unsupported variables before saving where practical.

---

## 9. Telegram presentation requirements

CineGate should intentionally support Telegram’s modern formatting capabilities rather than flattening everything to plain text.

Requirements include:

- Telegram message entities / formatting
- rich-message compatibility where applicable
- RTL handling for Arabic owner/user messages
- modern Telegram button styling where supported
- owner-editable messages should preserve supported formatting
- button creation should be centralized so presentation changes are consistent

Exact Bot API feature usage must be validated against the Bot API version/library selected during implementation.

---

## 10. Data/source-of-truth principle

Media should remain in Telegram.

Application database should primarily store metadata/indexes/references such as:

- movie identity
- normalized/search title
- year when available
- poster archive message reference
- quality
- quality archive message reference
- archive grouping/index state
- reward sessions
- deliveries
- deletion deadlines
- templates/settings
- audit/progress data as needed

Avoid downloading/re-uploading large movie files through the application server when Telegram-side copying can be used safely.

---

## 11. Reliability expectations

Plan for:

- duplicate archive events
- idempotent indexing
- duplicate reward callbacks
- duplicate delivery attempts
- application restart
- database restart
- Telegram temporary errors
- advertisement provider temporary errors
- failed deletion retry/reconciliation
- clear owner-visible errors/logging

---

## 12. Project governance

Every new work item must have a written plan in `plans/` before implementation.

Project memory, current status, active plan, progress log, and decisions must be updated continuously so we always know:

- what happened
- what changed
- what was added
- what failed
- where work stopped
- what remains
- exact next step

See `AGENTS.md`.

---

## 13. Implemented technical foundation

Plan 0003 established the application foundation.

Confirmed stack:

- Python 3.12
- aiogram 3.x for Telegram
- FastAPI + Uvicorn for HTTP/webhook/Mini App server surfaces
- PostgreSQL as persistent database
- SQLAlchemy 2 async ORM
- asyncpg driver
- Alembic migrations
- pytest / pytest-asyncio
- Ruff

Architecture remains one deployable application codebase separated by internal modules. Redis, Celery, Kafka/RabbitMQ, and a microservice split are intentionally **not** part of the current architecture because they are not yet required.

Implemented persistence foundation includes:

- `movies`
- `movie_qualities`
- `app_settings`
- `message_templates`

Database uniqueness constraints are deliberately used as part of future idempotency for archive indexing.

The archive parser is implemented as pure business logic and consumes already ordered archive messages in one pass. It does not sort/copy the full input internally. Out-of-order input is rejected explicitly.

CI verifies:

- Ruff
- pytest
- a real PostgreSQL 16 Alembic upgrade/downgrade/upgrade round-trip
- Python compileall

Last verified result for the completed foundation phase: **31 tests passed**.

See `plans/0003-application-foundation-and-parser.md`.

---

## 14. Implemented Telegram/archive ingestion

Plan 0004 completed the live Telegram transport and Archive Channel persistence layer.

Implemented:

- FastAPI `POST /telegram/webhook`
- constant-time validation of `X-Telegram-Bot-Api-Secret-Token`
- aiogram Dispatcher lifecycle inside the application runtime
- Archive Channel photo/video/video-document adaptation without downloading media
- DB-backed `archive_channel_id` and `owner_chat_id` runtime settings
- idempotent poster/quality persistence
- PostgreSQL row locking for rapid concurrent qualities of the same movie
- deterministic replacement of a newer duplicate resolution
- pending → indexed/orphan transitions
- owner indexing notification that sends once then edits the same message as quality count grows
- durable owner-notification progress so a duplicate webhook can retry a notification that failed after indexing already committed
- bounded convergence for concurrent owner-notification races
- webhook failures remain non-2xx when work must be retried

Current CI verification after Plan 0004:

- Ruff passed
- **52 tests passed**
- PostgreSQL 16 migrations `0001 → 0002 → 0003`
- full downgrade to base and upgrade back to head passed
- compileall passed

Important webhook sequencing rule:

Telegram documents that webhook updates can need sequence restoration using `update_id`, and webhook delivery can use multiple simultaneous connections. CineGate does not yet have a durable global update sequencer. Therefore initial production webhook registration must use **`max_connections=1`**. Do not increase it until a dedicated sequencing plan is implemented and tested.

This restriction applies to Telegram webhook delivery concurrency, not database connection capacity.

See `plans/0004-telegram-webhook-and-archive-indexer.md`.

---

## 15. Implemented search and movie page

Plan 0005 completed the pre-ad end-user flow.

Implemented:

- direct private-text search; no search button/mode required
- English-title normalization with typo tolerance
- PostgreSQL `pg_trgm` GiST KNN search; no Python full-catalog scan
- canonical poster-title search
- quality-caption title aliases, allowing an English video title to find a movie whose poster title is in another language
- release-year-aware ranking for duplicate titles
- safe handling of year-only movie titles such as `1917`
- result limits and bounded candidate pools
- durable single-current search session per Telegram user
- nonce-bound callbacks that invalidate stale keyboards
- rapid double-click single-winner movie opening
- Telegram `copyMessage` of the poster/info directly from Archive Channel
- actual-available-quality buttons only
- styled inline buttons
- Back navigation
- owner-editable search/no-result message bodies through `message_templates`
- cleanup of Telegram UI if DB persistence fails after a Telegram send/copy

Migrations:

- `0004`: pg_trgm + canonical-title GiST index
- `0005`: `user_search_sessions`
- `0006`: quality-title alias GiST index

Last Plan 0005 verification:

- Ruff passed
- **87 tests passed**
- migrations 0001→0006, full downgrade/restore passed
- compileall passed
- canonical and alias KNN queries verified index-eligible

See `plans/0005-search-and-movie-page.md`.

---

## 16. Pending decisions / information

Do not guess these:

1. Rewarded-ad network/provider.
2. Production deployment topology/host.
3. Initial-import UserBot library/implementation.
4. Final owner/admin menu layout.
5. Exact Telegram Bot API/client feature versions for rich-message capabilities.
6. Real-time archive edit/delete reconciliation behavior.

These should be resolved through explicit plans and recorded in `docs/DECISIONS.md`.
