# Plan 0006 — Reward sessions, delivery, and durable deletion

**Status:** In progress  
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

- [ ] exact user/movie/quality binding
- [ ] one active session per user
- [ ] different quality cannot replace active reward
- [ ] expired session allows new reward
- [ ] duplicate client completion idempotent
- [ ] duplicate provider confirmation idempotent
- [ ] provider-first then client → rewarded
- [ ] client-first then provider → rewarded
- [ ] wrong Telegram user cannot claim session
- [ ] invalid Mini App signature rejected
- [ ] stale Mini App auth_date rejected

### Mini App / AdsGram

- [ ] page refuses unknown/expired session
- [ ] page requires configured block ID
- [ ] client page contains Telegram + AdsGram SDK
- [ ] provider callback secret required
- [ ] wrong callback secret rejected
- [ ] callback with no active session is harmless

### Delivery

- [ ] rewarded exact quality is copied
- [ ] caption variables render
- [ ] %time% follows DB setting
- [ ] delivered message persists delete deadline
- [ ] duplicate delivery call does not send again
- [ ] Telegram delivery failure keeps reward reusable
- [ ] poster message is never scheduled for deletion

### Deletion

- [ ] due message deleted
- [ ] not-yet-due untouched
- [ ] already-missing message becomes deleted
- [ ] transient failure rescheduled with backoff
- [ ] restart recovery handles stale deleting rows
- [ ] batch bounded
- [ ] concurrent workers cannot claim same due row

### Quality gates

- [ ] Ruff
- [ ] pytest
- [ ] migrations apply / full downgrade / restore
- [ ] compileall

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

- [ ] production reward cannot be granted from client callback alone
- [ ] reward session is exact user/movie/quality
- [ ] provider callback is secret-protected
- [ ] valid reward survives delivery failure
- [ ] movie is copied from Archive Channel
- [ ] delivery caption is dynamic/editable
- [ ] only movie file is durably auto-deleted
- [ ] restart-safe deletion implemented
- [ ] ads-specific public values remain DB-configurable
- [ ] all checks pass
- [ ] two reviews documented
- [ ] memory/status/progress updated

## Implementation steps

- [x] 1. Create this plan before code.
- [ ] 2. Add optional AdsGram callback secret config.
- [ ] 3. Add reward/delivery schema migrations.
- [ ] 4. Implement reward-session service.
- [ ] 5. Implement Telegram Mini App init-data validation.
- [ ] 6. Implement AdsGram provider confirmation endpoint.
- [ ] 7. Implement Mini App HTML/JS route.
- [ ] 8. Connect quality callback to reward session/WebApp button.
- [ ] 9. Implement delivery caption renderer.
- [ ] 10. Implement exact quality delivery.
- [ ] 11. Implement durable deletion worker.
- [ ] 12. Wire worker into runtime lifecycle.
- [ ] 13. Add full integration/unit tests.
- [ ] 14. Run CI.
- [ ] 15. Correctness review/fixes.
- [ ] 16. Performance/complexity review/fixes.
- [ ] 17. Final CI.
- [ ] 18. Update project memory/docs.
- [ ] 19. Mark complete.

## Progress notes

### 2026-09-20

- Plan created before code.
- Telegram Mini App validation documentation reviewed.
- AdsGram Reward + Reward URL documentation reviewed.
- Production policy fixed at dual signal: client Telegram-validated completion + AdsGram server confirmation.

## Completion summary

Pending.
