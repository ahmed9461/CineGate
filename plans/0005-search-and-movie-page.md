# Plan 0005 — Direct movie search and movie-page UI

**Status:** In progress  
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

- [ ] exact match ranks first
- [ ] prefix match before fuzzy
- [ ] typo query finds intended movie
- [ ] low-similarity noise excluded
- [ ] only indexed movies returned
- [ ] movie without qualities excluded
- [ ] result limit bounded
- [ ] raw query length bounded
- [ ] hostile-looking SQL text remains data and causes no SQL execution

### Search sessions

- [ ] new session replaces previous nonce
- [ ] stale nonce cannot claim movie
- [ ] rapid two movie claims: only one wins
- [ ] movie must belong to stored result IDs
- [ ] failed copy can reset opening state
- [ ] Back state transition is single-winner

### Keyboards/callbacks

- [ ] callback data stays below 64 bytes
- [ ] styled result/quality buttons serialize
- [ ] only actual qualities are rendered
- [ ] quality order is stable

### Router/UI

- [ ] normal private text triggers search
- [ ] slash command does not trigger search
- [ ] no result sends configured default
- [ ] selecting movie copies correct archive poster
- [ ] old result UI is removed after successful poster copy
- [ ] rapid duplicate movie callback does not duplicate poster
- [ ] Back reconstructs prior results

### Quality gates

- [ ] Ruff
- [ ] pytest
- [ ] migration apply + rollback/restore
- [ ] compileall

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

- [ ] direct English text search works
- [ ] typo tolerance uses indexed PostgreSQL search
- [ ] results are relevant and bounded
- [ ] no-result path is clear
- [ ] movie callback is stale/rapid-safe
- [ ] poster copied from archive without downloading
- [ ] only real qualities shown
- [ ] Back works from durable session
- [ ] modern button styles supported
- [ ] all checks pass
- [ ] both reviews documented
- [ ] memory/status/progress updated

## Implementation steps

- [x] 1. Create this plan before code.
- [ ] 2. Add pg_trgm migration/index.
- [ ] 3. Add search-session migration/model.
- [ ] 4. Add float setting helper.
- [ ] 5. Implement bounded PostgreSQL search service.
- [ ] 6. Implement search session repository/state machine.
- [ ] 7. Implement callback data and centralized keyboards.
- [ ] 8. Implement user search/movie router.
- [ ] 9. Wire router into runtime.
- [ ] 10. Add PostgreSQL integration tests.
- [ ] 11. Add UI/router unit tests.
- [ ] 12. Run full CI.
- [ ] 13. Correctness review/fixes.
- [ ] 14. Performance/complexity review/fixes.
- [ ] 15. Re-run CI.
- [ ] 16. Update docs/memory/status.
- [ ] 17. Mark complete.

## Progress notes

### 2026-09-20

- Plan created before implementation.
- PostgreSQL trigram search selected to avoid full-catalog Python fuzzy scans.
- Modern Telegram button styling verified in current Bot API/aiogram docs.

## Completion summary

Pending.
