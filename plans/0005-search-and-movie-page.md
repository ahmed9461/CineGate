# Plan 0005 — Direct movie search and movie-page UI

**Status:** Completed  
**Created:** 2026-09-20  
**Last updated:** 2026-09-20

## Objective

Implement the end-user CineGate flow from direct English text search through selecting a movie and viewing its Archive Channel poster/info with only the available quality buttons.

The flow must remain safe under rapid repeated messages/callbacks and must not scan the entire movie catalog in Python.

## Context

Plans 0003–0004 provide:

- PostgreSQL movie/quality catalog
- secure Telegram webhook
- aiogram runtime
- Archive Channel references
- modern/legacy indexing
- duplicate/concurrency handling

Confirmed owner UX:

1. User opens bot and types movie name directly.
2. No separate search button/mode.
3. Search is English-title focused and typo tolerant.
4. If several close matches exist, show buttons.
5. Selecting a movie removes/replaces old results and copies the original poster/info from Archive Channel.
6. Under poster show only actual available qualities plus Back.
7. Next phase will connect quality selection to rewarded ads.

Telegram Bot API 10.3 and current aiogram support styled inline buttons:
- `primary`
- `success`
- `danger`
- default transparent/app style

References reviewed:
- https://core.telegram.org/bots/api#inlinekeyboardbutton
- https://docs.aiogram.dev/en/latest/api/enums/button_style.html

## Search design

Use PostgreSQL `pg_trgm`.

### Why

- typo tolerance is performed by the database index
- no full-catalog Python scan
- no extra search service
- no RapidFuzz dependency required
- bounded candidate set before application ranking

### Database

Migration adds:

- `CREATE EXTENSION IF NOT EXISTS pg_trgm`
- GiST trigram index on `movies.normalized_title`

Search uses trigram distance `<->` to fetch a bounded nearest-neighbor candidate set.

Application ranking after the bounded SQL query:

1. exact normalized title
2. prefix match
3. substring/token-compatible match
4. fuzzy trigram score

Only `status='indexed'` movies with at least one quality may appear.

## Search input safety

- raw text maximum: 128 characters
- whitespace-only text ignored
- slash commands are not treated as searches
- normalized title must be non-empty
- parameterized SQL only
- no eval/shell/dynamic SQL fragments from user input
- candidate query always bounded
- result count bounded to 1..10
- very short queries avoid broad low-confidence fuzzy matches

Default search settings (DB-overridable later):

- `search_result_limit = 6`
- `search_similarity_threshold = 0.32`
- max candidate pool = 30

## Search session state

Rapid callbacks and Back navigation require a tiny durable per-user UI state.

Add `user_search_sessions` keyed by Telegram user ID:

- `telegram_user_id` PK
- `nonce` short random token
- `raw_query`
- `normalized_query`
- `result_movie_ids JSONB`
- `state`: results / opening / movie / returning
- `selected_movie_id` nullable
- `result_message_id` nullable
- `poster_message_id` nullable
- `updated_at`

There is only one current search session per user, so this table is bounded by users rather than searches.

The nonce is included in callback data so old keyboards become harmless after a new search.

## Rapid callback state machine

### Movie selection

Transaction:

- lock user search session
- verify user + nonce + state=results
- verify selected movie is among stored result IDs
- set state=opening

Network:

- copy poster from Archive Channel with quality keyboard

Then transaction:

- if nonce/state still valid, set state=movie and save copied poster message id
- otherwise delete the just-created stale poster

Only one rapid click can claim `results → opening`.

### Back

Transaction:

- claim `movie → returning`

Network:

- send reconstructed results from stored IDs
- delete poster

Then:

- `returning → results` and store new result message id

### New search while old action is running

New search replaces nonce/session.

Any late action with old nonce must fail finalization and delete any UI it created.

## Callback data

Keep callback data compact and below Telegram's 64-byte limit.

- movie: `m:<nonce>:<movie_id>`
- back: `b:<nonce>`
- quality: `q:<nonce>:<movie_id>:<quality>`

Do not encode raw user query into callback data.

## UI defaults

### Results text

```
وجدنا %count% نتائج بحث ✅️

من الأزرار التالية اختر الفيلم الذي تريده أو اكتب اسم فيلم آخر لإعادة البحث.
```

Buttons show:

`<title> (<year>)` when year exists.

### No results

Current confirmed owner default:

```
عذرا لم أجد نتائج بحث ‼️

هذا يعني اما الفيلم غير متوفر في ذاكرتي او ان نص البحث غير دقيق ، حاول كتابة الاسم الصحيح و اذا مازالت تظهر هذه الرسالة ف هذا يعني ان الفيلم غير متوفر.
```

### Quality keyboard

- quality buttons: `primary`
- Back: default/neutral
- future Watch Ad button: `success`

Button construction must be centralized.

## Telegram formatting

This phase does not build the owner template editor, but UI rendering must not prevent it.

- copied Archive poster preserves Telegram's original message/caption formatting
- button renderer supports current styled buttons
- template persistence already supports entities/rich-message JSON
- full owner rich-message editor remains Phase 8/9

## Stale Archive references

If poster copy fails because the Archive message is unavailable:

- do not leave search session stuck in opening
- reset session to results if still current
- send/answer a safe temporary error
- log the movie/archive reference for owner diagnosis

Do not silently delete catalog data in this phase.

## Data/schema impact

Migration 0004:

- enable `pg_trgm`
- add trigram GiST index

Migration 0005:

- create `user_search_sessions`

No reward/delivery data yet.

## Tests

### Search service

- [x] exact match ranks first
- [x] prefix match before fuzzy
- [x] typo query finds intended movie
- [x] low-similarity noise excluded
- [x] only indexed movies returned
- [x] movie without qualities excluded
- [x] result limit bounded
- [x] raw query length bounded
- [x] hostile-looking SQL text remains data and causes no SQL execution

### Search sessions

- [x] new session replaces previous nonce
- [x] stale nonce cannot claim movie
- [x] rapid two movie claims: only one wins
- [x] movie must belong to stored result IDs
- [x] failed copy can reset opening state
- [x] Back state transition is single-winner

### Keyboards/callbacks

- [x] callback data stays below 64 bytes
- [x] styled result/quality buttons serialize
- [x] only actual qualities are rendered
- [x] quality order is stable

### Router/UI

- [x] normal private text triggers search
- [x] slash command does not trigger search
- [x] no result sends configured default
- [x] selecting movie copies correct archive poster
- [x] old result UI is removed after successful poster copy
- [x] rapid duplicate movie callback does not duplicate poster
- [x] Back reconstructs prior results

### Quality gates

- [x] Ruff
- [x] pytest
- [x] migration apply + rollback/restore
- [x] compileall

## Review #1 — correctness

Review:

- ranking
- session-state transitions
- callback ownership/nonce
- stale UI cleanup
- archive copy error recovery
- Telegram callback answers
- all imports/conditions
- SQL query safety

## Review #2 — performance / complexity

Review:

- query plan/index use
- bounded candidate counts
- DB round trips
- session table growth
- no Python full-catalog scans
- no unnecessary cache/search service
- rapid callback contention
- network calls outside DB transactions

## Acceptance criteria

- [x] direct English text search works
- [x] typo tolerance uses indexed PostgreSQL search
- [x] results are relevant and bounded
- [x] no-result path is clear
- [x] movie callback is stale/rapid-safe
- [x] poster copied from archive without downloading
- [x] only real qualities shown
- [x] Back works from durable session
- [x] modern button styles supported
- [x] all checks pass
- [x] both reviews documented
- [x] memory/status/progress updated

## Implementation steps

- [x] 1. Create this plan before code.
- [x] 2. Add pg_trgm migration/index.
- [x] 3. Add search-session migration/model.
- [x] 4. Add float setting helper.
- [x] 5. Implement bounded PostgreSQL search service.
- [x] 6. Implement search session repository/state machine.
- [x] 7. Implement callback data and centralized keyboards.
- [x] 8. Implement user search/movie router.
- [x] 9. Wire router into runtime.
- [x] 10. Add PostgreSQL integration tests.
- [x] 11. Add UI/router unit tests.
- [x] 12. Run full CI.
- [x] 13. Correctness review/fixes.
- [x] 14. Performance/complexity review/fixes.
- [x] 15. Re-run CI.
- [x] 16. Update docs/memory/status.
- [x] 17. Mark complete.

## Progress notes

### 2026-09-20 — implementation

- Plan created before implementation.
- PostgreSQL trigram search selected to avoid full-catalog Python fuzzy scans.
- Added `pg_trgm` GiST indexes for both canonical poster titles and quality-caption titles.
- Quality-caption English titles act as local aliases, solving cases where the poster title is Spanish/French/etc. while the quality caption is English.
- Added durable one-current-search session per Telegram user.
- Added compact nonce-bound callback data.
- Added styled result and quality keyboards.
- Added direct private-text search, movie selection, Archive Channel poster copy, quality buttons, and Back navigation.
- Added owner-editable search/no-result message-body lookup.
- Wired user router into application runtime.

### 2026-09-20 — review #1: correctness

Findings and fixes:

- Found the edge case movie title `1917`: generic year stripping could erase the whole title. Added trailing-release-year extraction that preserves year-only titles while still parsing `1917 2019` correctly.
- Search originally considered canonical poster titles only. Real archive evidence requires English quality-caption titles to be searchable aliases; added indexed quality aliases.
- First concurrent searches for a brand-new user could race row creation. Added a PostgreSQL transaction advisory lock scoped to that Telegram user only.
- Stale result keyboards are protected with a random nonce and stored result IDs.
- Rapid double-click on a movie is single-winner and produces one poster copy.
- New search invalidates old callbacks.
- Added cleanup if PostgreSQL fails after Telegram already sent a results message or copied a poster, preventing orphan UI on webhook retry.
- No-result text was verified as database-editable.
- Slash commands are not treated as movie searches.

### 2026-09-20 — review #2: performance / complexity

Findings and decisions:

- No Python full-catalog fuzzy scan.
- PostgreSQL KNN trigram queries are bounded and index-backed.
- Tests verify both canonical and alias KNN queries are eligible for their GiST indexes.
- Candidate sets are capped before Python ranking.
- Search result limit is bounded to at most 10.
- Only one durable search-session row exists per user; searches replace the row rather than creating an unbounded history.
- Network calls occur outside the session-state locking transaction.
- No Redis, Elasticsearch, Meilisearch, or extra cache/search service was added.
- Movie poster delivery uses Telegram `copyMessage`; media is never downloaded by CineGate.

### 2026-09-20 — final verification

GitHub Actions with PostgreSQL 16:

- Ruff: **all checks passed**
- pytest: **87 passed**
- Alembic migrations `0001 → 0006`: passed
- full downgrade to base and restore to head: passed
- Python compileall: passed
- KNN trigram index eligibility checks: passed

Two warnings are dependency deprecation notices from FastAPI/Starlette test internals, not CineGate code.

## Completion summary

Plan 0005 is complete.

CineGate now supports the full pre-ad user path:

`type English title → ranked typo-tolerant results → select movie → copied Archive poster/info → available quality buttons → Back`

**Next exact step:** create Plan 0006 before code for quality reward sessions, provider-neutral Mini App handoff, verified reward completion, Telegram archive delivery, and durable timed deletion. AdsGram-specific credentials/Block ID remain deferred until the external platform is finalized.
