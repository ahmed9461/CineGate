# Plan 0006 — Reward sessions, delivery, and durable deletion

**Status:** Completed  
**Created:** 2026-09-20  
**Last updated:** 2026-09-20

## Objective

Implement the durable path from an exact selected movie quality to:

1. a one-user/one-quality reward session
2. Telegram Mini App handoff
3. verified rewarded-ad completion
4. one delivery attempt state machine
5. copy of the exact Archive Channel quality
6. owner-editable delivery caption variables
7. durable automatic deletion of only the delivered movie message

AdsGram production Block ID/platform values may remain unset until final external setup, but the integration boundary and Mini App must be ready.

## Official integration facts reviewed

### Telegram Mini Apps

Telegram requires server-side validation of `Telegram.WebApp.initData`. Data from `initDataUnsafe` must not be trusted.

aiogram provides `safe_parse_webapp_init_data` for this validation.

Sources:

- https://core.telegram.org/bots/webapps
- https://docs.aiogram.dev/en/latest/utils/web_app.html

### AdsGram

Current AdsGram Reward behavior:

- Rewarded `AdController.show()` resolves after the rewarded ad completes.
- Reward URL is an optional server-side confirmation mechanism for Mini Apps.
- After client reward, AdsGram can issue an HTTPS GET to the configured Reward URL with the user's Telegram ID.
- Debug views do not trigger Reward URL.

Sources:

- https://docs.adsgram.ai/publisher/reward-interstitial-integration
- https://docs.adsgram.ai/publisher/reward-interstitial-code-examples
- https://docs.adsgram.ai/publisher/get-block-id

## Production verification policy

CineGate must **not** grant production reward from a browser/JavaScript callback alone.

A production reward becomes valid only when both are present for the same active user session:

1. **client completion** — Mini App calls CineGate after AdsGram `show()` resolves, using valid Telegram `initData`
2. **provider confirmation** — AdsGram Reward URL callback reaches CineGate for that Telegram user

The two signals may arrive in either order.

A static high-entropy AdsGram callback secret is required in environment configuration because the documented Reward URL callback contains the Telegram user ID but no documented cryptographic signature.

The secret must never be stored in normal app settings.

## One active reward per user

Because the AdsGram Reward URL identifies the user, not a CineGate session ID:

- a Telegram user may have only one active reward session at a time
- clicking another quality while an active session exists returns/reuses that active session rather than replacing it
- this prevents an old provider callback from being applied to a newly replaced quality
- reward sessions expire

## Reward session states

Persist:

- `pending`
- `client_completed`
- `provider_confirmed`
- `rewarded`
- `delivering`
- `delivered`
- `expired`

Timestamps are also stored so state can be reconstructed/audited.

The session binds:

- UUID token
- Telegram user ID
- movie ID
- exact movie_quality row
- quality string
- created/expires
- client completion
- provider confirmation
- reward time
- delivery start/delivery completion

A partial unique index enforces one active reward session per Telegram user.

## Mini App

Route:

- `GET /miniapp/reward/{session_id}`

Page:

- Telegram WebApp script
- AdsGram SDK script
- current non-secret `adsgram_block_id` from DB
- clear movie/quality context
- expected “Watch ad” action
- after AdsGram Reward resolves, POST valid `Telegram.WebApp.initData` to CineGate claim endpoint
- if provider server confirmation has not arrived yet, poll/retry briefly
- close/finish only after server reports reward/delivery state

No ad can be marked rewarded merely because this page opened.

## Reward API

### Client claim

`POST /api/rewards/{session_id}/claim`

Body:

- `init_data`

Server:

- validate Telegram signature using bot token
- require user in init data
- require init_data auth_date freshness
- require Telegram user == session user
- record client-completed timestamp idempotently
- if provider confirmation already exists, transition to rewarded
- attempt delivery if rewarded
- otherwise return waiting-for-provider state

### AdsGram Reward URL

`GET /providers/adsgram/reward/{callback_secret}?userid=[userId]`

Server:

- constant-time callback secret comparison
- locate that user's one active non-expired session
- mark provider-confirmed idempotently
- if client completion already exists, transition to rewarded
- do not trust user-controlled session IDs on this provider callback

Operational deployment must avoid logging the secret-bearing callback URL or redact it at the reverse proxy.

## Runtime non-secret settings

DB settings:

- `public_base_url`
- `adsgram_block_id`
- `reward_session_seconds` default 600
- `miniapp_init_data_max_age_seconds` default 600
- `movie_delete_seconds` default 120

These are normal runtime settings and must not move to `.env`.

Environment secret:

- `CINEGATE_ADSGRAM_CALLBACK_SECRET` (optional until AdsGram production integration is enabled)

## Quality click UX

When user clicks an actual quality:

1. validate current search nonce/movie/quality
2. create or return active reward session
3. if another quality is already active, do not silently switch it
4. send ad requirement message
5. if Mini App/public URL/block ID are configured, show `مشاهدة الإعلان` WebApp button
6. Back/current movie UI remains valid

Default text concept:

```
🎬 %movie%
🎞 الجودة: %quality%

عليك مشاهدة إعلان قصير قبل استلام الجودة المطلوبة.

[ مشاهدة الإعلان ]
```

## Delivery caption

Default:

```
%movie% %year% %quality%

مهم جدا
يرجى تحويل الفيديو الى رسائل المحفوظة او اي محادثة اخرى لانه سوف يتم حذفه بعد %time%
```

Required variables:

- `%movie%`
- `%year%`
- `%quality%`
- `%time%`

`%time%` is generated from current `movie_delete_seconds`, so changing deletion timing never requires editing the whole template.

Delivery caption must stay within Telegram caption limits. Invalid owner templates must fail safely to the known default.

## Delivery state

Add `deliveries` table:

- id
- reward_session_id unique
- telegram_user_id
- movie_quality_id
- status: pending / sending / sent / deleting / deleted
- telegram_message_id nullable
- send_started_at nullable
- sent_at nullable
- delete_at nullable
- next_attempt_at nullable
- delete_started_at nullable
- deleted_at nullable
- attempts
- last_error nullable

### Delivery

When reward becomes valid:

- transaction-lock reward session
- if already delivered, return existing delivery state
- if currently delivering, return processing
- transition to delivering/sending
- perform Telegram `copyMessage` **outside** DB transaction
- use exact Archive Channel quality message
- override caption with rendered delivery template
- do not set `protect_content=True`; user is explicitly instructed to forward/save before expiry
- on success persist Telegram message ID and delete deadline
- on Telegram API failure return reward to `rewarded`, leaving user eligible to retry without another ad

There is an unavoidable tiny crash window after Telegram accepted a copy but before its returned message ID is committed. This limitation must be documented; Telegram Bot API provides no idempotency key for `copyMessage`.

## Durable deletion worker

Run a lightweight background worker in the same application process.

- query due `sent` deliveries in bounded batches
- claim rows with `FOR UPDATE SKIP LOCKED`
- mark `deleting`, commit, then call Telegram outside transaction
- success → `deleted`
- “already gone / cannot find message” → treat as deleted
- transient Telegram/API error → status back to `sent`, exponential bounded retry via `next_attempt_at`
- restart recovery resets stale `deleting` rows to retryable state
- only delivered movie message is deleted; poster/info message is never referenced by the deletion worker

No Celery/Redis is required for this timer.

## Tests

### Reward sessions

- [x] exact user/movie/quality binding
- [x] one active session per user
- [x] different quality cannot replace active reward
- [x] expired session allows new reward
- [x] duplicate client completion idempotent
- [x] duplicate provider confirmation idempotent
- [x] provider-first then client → rewarded
- [x] client-first then provider → rewarded
- [x] wrong Telegram user cannot claim session
- [x] invalid Mini App signature rejected
- [x] stale Mini App auth_date rejected

### Mini App / AdsGram

- [x] page refuses unknown/expired session
- [x] page requires configured block ID
- [x] client page contains Telegram + AdsGram SDK
- [x] provider callback secret required
- [x] wrong callback secret rejected
- [x] callback with no active session is harmless

### Delivery

- [x] rewarded exact quality is copied
- [x] caption variables render
- [x] %time% follows DB setting
- [x] delivered message persists delete deadline
- [x] duplicate delivery call does not send again
- [x] Telegram delivery failure keeps reward reusable
- [x] poster message is never scheduled for deletion

### Deletion

- [x] due message deleted
- [x] not-yet-due untouched
- [x] already-missing message becomes deleted
- [x] transient failure rescheduled with backoff
- [x] restart recovery handles stale deleting rows
- [x] batch bounded
- [x] concurrent workers cannot claim same due row

### Quality gates

- [x] Ruff
- [x] pytest
- [x] migrations apply / full downgrade / restore
- [x] compileall

## Review #1 — correctness

Inspect:

- dual proof reward logic
- Mini App identity and auth-date validation
- one-active-session rule
- exact-quality binding
- all state transitions
- delivery retry semantics
- deletion-only movie message
- restart recovery
- callback replay/duplicates
- Telegram error classes

## Review #2 — performance / complexity

Inspect:

- indexes/partial uniqueness
- DB round trips
- lock scope
- network calls outside transactions
- deletion batch size
- worker sleep/backoff
- no unnecessary broker/task queue
- no file download/re-upload

## Acceptance criteria

- [x] production reward cannot be granted from client callback alone
- [x] reward session is exact user/movie/quality
- [x] provider callback is secret-protected
- [x] valid reward survives delivery failure
- [x] movie is copied from Archive Channel
- [x] delivery caption is dynamic/editable
- [x] only movie file is durably auto-deleted
- [x] restart-safe deletion implemented
- [x] ads-specific public values remain DB-configurable
- [x] all checks pass
- [x] two reviews documented
- [x] memory/status/progress updated

## Implementation steps

- [x] 1. Create this plan before code.
- [x] 2. Add optional AdsGram callback secret config.
- [x] 3. Add reward/delivery schema migrations.
- [x] 4. Implement reward-session service.
- [x] 5. Implement Telegram Mini App init-data validation.
- [x] 6. Implement AdsGram provider confirmation endpoint.
- [x] 7. Implement Mini App HTML/JS route.
- [x] 8. Connect quality callback to reward session/WebApp button.
- [x] 9. Implement delivery caption renderer.
- [x] 10. Implement exact quality delivery.
- [x] 11. Implement durable deletion worker.
- [x] 12. Wire worker into runtime lifecycle.
- [x] 13. Add full integration/unit tests.
- [x] 14. Run CI.
- [x] 15. Correctness review/fixes.
- [x] 16. Performance/complexity review/fixes.
- [x] 17. Final CI.
- [x] 18. Update project memory/docs.
- [x] 19. Mark complete.

## Progress notes

### 2026-09-20 — implementation

- Plan created before code.
- Telegram Mini App validation documentation reviewed.
- AdsGram Reward + Reward URL documentation reviewed.
- Production policy fixed at dual signal: Telegram-validated client completion + AdsGram server confirmation.
- Added optional secret bootstrap setting for the provider callback.
- Added migrations 0007 and 0008.
- Added durable reward sessions and deliveries.
- Added Mini App HTML/JS and provider callback routes.
- Connected quality selection to a WebApp reward prompt.
- Added dynamic delivery-caption rendering.
- Added Telegram-side quality copy and persistent delete deadline.
- Added in-process durable deletion worker with retry/backoff and restart reconciliation.

### 2026-09-20 — review #1: correctness/security

Findings and fixes:

- Reward state is bound to the exact Telegram user, movie, and `movie_qualities` row.
- Only one active reward session per Telegram user is permitted because AdsGram's documented Reward URL identifies the user but not a CineGate session.
- Client-only completion never grants delivery; server provider proof is also required.
- Both provider→client and client→provider ordering are idempotent and tested.
- Signed Telegram `initData` and `auth_date` freshness are validated server-side.
- Mini App settings embedded in JavaScript are escaped to prevent script injection.
- A provider-only confirmation does **not** skip the current ad, reducing risk from a delayed user-only provider callback.
- A client-completed session can resume verification without forcing another ad.
- Earned `rewarded` state does not expire merely because the original ad-session TTL elapsed.
- Rapid repeated quality clicks create one prompt; a different quality cannot silently replace an active reward.
- Telegram delivery failure returns the session to `rewarded`; the user is not charged another ad.
- Delivery copy is idempotent at the DB state level and uses the exact Archive Channel quality message.
- `protect_content=False` is intentional so the user can save/forward before expiry.
- Invalid owner delivery templates fall back to a known-safe default.
- Cosmetic Telegram cleanup no longer creates webhook retries if cleanup itself temporarily fails.
- The tiny post-`copyMessage`/pre-DB-commit crash window remains documented because Telegram offers no copy idempotency key.

### 2026-09-20 — review #2: performance/recovery

Findings and fixes:

- No Redis/Celery/broker was added.
- All Telegram/network I/O stays outside long DB transactions.
- One reward row and one delivery row represent each rewarded request.
- Due deletion is bounded and claimed with `FOR UPDATE SKIP LOCKED`.
- Deletion concurrency is bounded.
- Transient Telegram deletion failures use bounded exponential backoff.
- Stale `sending` and `deleting` states are reconciled periodically, not only at process startup.
- A single post-Telegram DB persistence failure no longer kills the worker.
- Temporary DB outage does not permanently stop the deletion loop.
- Telegram's 48-hour deletion limitation is enforced honestly: an impossible/permanent deletion becomes `delete_failed` instead of being falsely recorded as deleted.
- Missing messages are considered successfully gone; other permanent BadRequest/Forbidden failures are retained as `delete_failed` for owner diagnostics.
- Movie delete duration is bounded below Telegram's 48-hour deletion window.

### 2026-09-20 — final verification

Latest full code verification before documentation-only closeout:

- Ruff: **all checks passed**
- pytest: **137 passed**
- PostgreSQL migrations: **0001 → 0008 passed**
- full downgrade to base and restore to head: **passed**
- Python compileall: **passed**

The two test warnings are dependency deprecation notices from FastAPI/Starlette internals, not CineGate code.

### Known external limitation

AdsGram's documented Mini App Reward URL provides Telegram `userId` but no per-view CineGate session identifier or documented cryptographic signature. CineGate mitigates this with:

- one active reward per user
- Telegram-signed client identity
- dual client/provider proof
- provider-only state never skipping the current ad
- high-entropy callback bearer secret

If the provider later exposes a signed per-view/session token, that mechanism should replace the current user-only provider binding through a new plan.

### Telegram deletion limitation

Telegram only permits deleting messages sent less than 48 hours ago. CineGate schedules well below that limit and retries durably, but a server outage longer than the Telegram window can make deletion impossible. Such rows become `delete_failed`; they are not falsely marked deleted.

See `docs/SECURITY.md`.

## Completion summary

Plan 0006 is complete.

Implemented the full rewarded-delivery path:

`quality → reward session → Mini App → dual verification → Archive copy → persistent expiry → durable deletion`

**Next exact step:** create Plan 0007 before implementing the owner/admin control center for runtime settings, message templates, diagnostics, and AdsGram public configuration.
