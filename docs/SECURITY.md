# CineGate Security and Operations Notes

**Last updated:** 2026-09-20

This file records security-sensitive operational requirements that must not live only in chat history.

## Telegram webhook ordering

Production webhook registration must use:

`max_connections=1`

until CineGate has a durable global update sequencer.

Archive grouping is sequence-sensitive. Do not increase Telegram webhook delivery concurrency merely for throughput without implementing and testing ordering first.

## Telegram webhook secret

`CINEGATE_WEBHOOK_SECRET` is sensitive bootstrap configuration.

- never commit the real value
- validate `X-Telegram-Bot-Api-Secret-Token`
- never put the bot token in the webhook URL
- do not log secret headers

## Telegram Mini App identity

Never trust `Telegram.WebApp.initDataUnsafe`.

CineGate validates signed `Telegram.WebApp.initData` on the server using the bot token and also checks `auth_date` freshness.

A Mini App page opening is **not** proof of reward.

## AdsGram reward verification

Current AdsGram Mini App Reward URL documentation supplies the user's Telegram ID but does not document a per-view CineGate session identifier or provider signature.

CineGate therefore requires two independent signals before reward delivery:

1. Telegram-signed Mini App client completion
2. AdsGram server Reward URL confirmation

Because the provider callback identifies only the Telegram user:

- only one reward session may be active per Telegram user
- a provider-only confirmation never lets the user skip the current ad
- an already client-completed session may resume without forcing another ad
- earned `rewarded` state survives a later Telegram delivery failure

This reduces cross-session callback ambiguity, but the provider's user-only callback is an external limitation. If AdsGram later offers a signed per-view/session token, prefer it and create a new implementation plan before changing the verification model.

## AdsGram callback secret

`CINEGATE_ADSGRAM_CALLBACK_SECRET` is an optional production secret.

The Reward URL endpoint currently uses it as a bearer path token because AdsGram's documented callback interface does not provide a signature.

Important:

- generate a high-entropy URL-safe value
- never commit it
- rotate it if exposed
- do not expose it in owner/admin settings
- reverse-proxy and Uvicorn access logging must not retain the full secret-bearing callback URL in production logs

The production deployment plan must explicitly configure request-log redaction or disable access logging for this endpoint.

## Reward public settings

These are not secrets and belong in persistent DB settings:

- `public_base_url`
- `adsgram_block_id`
- `reward_session_seconds`
- `miniapp_init_data_max_age_seconds`
- `movie_delete_seconds`

## Telegram media handling

CineGate does not download movie files for search/index/delivery.

Movie media remains in Telegram. Delivery uses Telegram-side `copyMessage` from the private Archive Channel.

The delivered movie message must use:

`protect_content=False`

because the product explicitly tells the user to forward/save the movie before automatic deletion.

## Movie deletion window

Telegram Bot API only permits deleting messages sent less than 48 hours ago.

CineGate:

- bounds configured deletion duration below 48 hours
- persists the deletion deadline
- retries transient failures
- reconciles stale `sending` / `deleting` states
- marks an impossible/permanent deletion as `delete_failed` instead of falsely marking it deleted

A prolonged outage can therefore make deletion impossible after Telegram's 48-hour limit. `delete_failed` records must be visible to future owner diagnostics/admin tooling.

## Delivery crash window

Telegram Bot API does not provide an idempotency key for `copyMessage`.

There is a small unavoidable crash window:

1. Telegram accepts and creates the copied movie message
2. CineGate crashes before persisting Telegram's returned message ID

After stale-state recovery, retrying can create another copy because CineGate cannot prove the first copy's ID.

This limitation must remain documented. Do not pretend exactly-once Telegram delivery is guaranteed.

## Database and concurrency

- PostgreSQL constraints/transactions are authoritative.
- Use per-user/per-movie locks where needed; avoid global in-memory correctness locks.
- Telegram/network I/O should stay outside long database transactions.
- Durable deletion workers use `FOR UPDATE SKIP LOCKED`.
- Redis/Celery/message brokers are not currently required and must not be added without a measured need.

## Secrets never committed

Never commit:

- bot tokens
- production database credentials
- webhook secrets
- AdsGram callback secret
- Telegram UserBot session files
- private keys or certificates containing secrets


## Historical UserBot importer

The historical importer is a one-time operational tool and does not run inside the normal CineGate service.

Secrets/bootstrap:

- `CINEGATE_TELEGRAM_API_ID`
- `CINEGATE_TELEGRAM_API_HASH`
- Telethon `.session` / `.session-journal` files

Requirements:

- never commit UserBot session material
- never log API hash, login codes, 2FA password, or session contents
- keep the default session under the ignored `sessions/` path
- custom session locations remain the operator's responsibility, though `*.session` and `*.session-journal` are ignored globally
- run UserBot auth/import only from a trusted machine/server account
- disconnect the UserBot after each CLI command

Content protection:

- CineGate does not bypass Telegram content protection
- the authorized owner must temporarily disable source-channel forwarding protection before migration
- the Archive Channel itself must also have content protection disabled, because CineGate later uses Bot API `copyMessage` to deliver media to users
- if Telegram reports protected forwarding, the importer pauses/stops rather than attempting a workaround

Media handling:

- the importer forwards Telegram messages server-side
- it does not call `download_media`
- it does not materialize movie files on the CineGate host
- source→archive message references/checkpoints are the durable state, not file bytes

Crash/retry model:

- Telegram forwarding and PostgreSQL mapping commit are separate systems
- if Telegram forwards successfully and the process dies before DB commit, the next run reconciles Archive forward metadata before forwarding more data
- importer state/mapping is idempotent and protected by a PostgreSQL advisory lock per source/archive pair
- historical mappings suppress late per-film owner notifications even after the import has completed
- progress reporting is best-effort and must never stop the transfer itself

Operational note:

- `verify` is read-only with respect to Telegram and checks stored mappings against Archive forward metadata
- `status` requires only PostgreSQL and does not require Telegram API credentials
