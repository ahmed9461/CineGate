# Plan 0009 — Launch hardening and deployment

**Status:** Completed
**Created:** 2026-09-21  
**Last updated:** 2026-09-21

## Objective

Harden CineGate for controlled production launch without adding unnecessary infrastructure.

This phase covers abuse protection, production-safe logging, liveness/readiness, webhook operations, backup/restore/runbook, Archive edit reconciliation, deletion/integrity auditing, and final rapid-click/restart/load validation.

## Current baseline

Plans 0003–0008 are complete.

Latest verified baseline:

- Ruff passes
- 230 tests pass
- PostgreSQL migrations 0001→0010 pass
- full downgrade/restore passes
- compileall passes
- historical importer is separate and resumable

## Telegram platform facts reviewed

Official Telegram Bot API 10.3 currently exposes:

- `channel_post`
- `edited_channel_post`

The Bot API `Update` object does **not** expose a channel-message deletion update.

Telegram's MTProto update stream does expose `updateDeleteChannelMessages`.

Therefore:

- Archive **edits** can reconcile in real time through the existing Bot API webhook.
- Archive **deletions** cannot honestly be called real-time while CineGate intentionally avoids a permanent MTProto/UserBot daemon.
- Deletion reconciliation will use a bounded integrity-audit operational command/tool and owner diagnostics.
- Do not introduce a permanent UserBot solely to simulate a Bot API capability that does not exist.

Official references reviewed 2026-09-21:

- https://core.telegram.org/bots/api
- https://core.telegram.org/api/updates

## Scope

### In scope

- single-process application abuse/rate limiting
- search/callback rapid-click protections beyond state-machine idempotency
- bounded in-memory limiter with LRU/expiry
- structured JSON application logs
- secret/path redaction
- safe request/access logging
- liveness and database readiness endpoints
- worker-health readiness check
- webhook set/status/delete operational CLI
- webhook configured with `max_connections=1`
- explicit allowed updates
- webhook status verification
- startup configuration validation
- real-time `edited_channel_post` reconciliation
- bounded Archive integrity/deletion audit tooling
- backup/restore scripts/runbook
- provider-neutral deployment runbook
- restart/load/race tests
- final launch checklist

### Out of scope

- horizontal multi-instance deployment
- Redis distributed rate limiter
- global webhook sequencer
- permanent MTProto/UserBot daemon
- production AdsGram credentials themselves
- advanced Rich Message editor
- visual button-style editor

## Architecture rule

Current launch topology is one CineGate application process plus PostgreSQL.

This is deliberate:

- webhook delivery remains `max_connections=1`
- current state machines use PostgreSQL for durable correctness
- in-memory rate limiting protects abuse but is not a correctness primitive
- no Redis/Celery/message broker until a measured requirement justifies it

## 1. Abuse/rate limiting

Implement a small monotonic token/sliding-window limiter with bounded memory.

Protect:

- direct text searches
- movie/result callbacks
- quality/reward callbacks
- Mini App reward claim endpoint

Do not rate-limit:

- Telegram archive channel ingestion
- owner admin actions by the same public-user thresholds
- provider server callback using the user limiter

Initial limits must be conservative and DB/runtime configurable where useful.

Suggested defaults:

- search: 8 requests / 10 seconds per user
- callback actions: 20 / 10 seconds per user
- reward claim: 20 / 30 seconds per user/session

Behavior:

- Telegram message/callback abuse gets a concise cooldown response
- HTTP reward abuse gets 429 + Retry-After
- limiter state expires automatically
- key count is bounded
- no correctness state relies on limiter survival across restart

## 2. Structured/redacted logging

Use Python stdlib logging with a JSON formatter.

Required fields where available:

- timestamp
- level
- logger
- event
- request_id/update_id
- telegram user/chat IDs when operationally useful
- movie/reward/delivery/import identifiers
- duration_ms
- exception class

Redact/never log:

- bot token
- webhook secret
- AdsGram callback secret
- database password/URL credentials
- Telegram API hash
- UserBot session contents
- Mini App initData
- login codes / 2FA
- secret-bearing AdsGram callback URL segment

HTTP request logging:

- log sanitized route labels, not raw secret paths
- disable or avoid raw Uvicorn access logs in the production runbook
- provider callback path must render as `/providers/adsgram/reward/[REDACTED]`

## 3. Health/readiness

Keep lightweight liveness:

- `GET /healthz` → process alive

Add:

- `GET /readyz`

Readiness verifies:

- PostgreSQL `SELECT 1`
- deletion worker task exists and has not crashed
- core runtime is initialized

Readiness must not depend on Telegram/AdsGram external availability.

## 4. Webhook operations CLI

Add operational command:

`python -m cinegate.ops webhook <set|status|delete>`

`set`:

- read public_base_url from DB
- register `/telegram/webhook`
- use configured webhook secret
- force `max_connections=1`
- explicit allowed updates:
  - message
  - callback_query
  - channel_post
  - edited_channel_post
- do not drop pending updates unless explicitly requested

`status`:

- call getWebhookInfo
- report URL hostname/path without exposing secrets
- pending_update_count
- last_error_date/message
- max_connections
- allowed_updates
- verify URL/connection/update configuration against expected CineGate settings

`delete`:

- remove webhook
- default does not drop pending updates

## 5. Archive edit reconciliation

Add handler for `edited_channel_post`.

For configured Archive Channel:

- poster edit reparses and updates same movie row
- quality-caption edit reparses exact quality message
- invalid edit must not silently corrupt existing good association
- if an indexed quality edit becomes invalid/ambiguous, mark/reconcile safely rather than linking it to the wrong movie
- if poster/quality identifiers change, search/delivery references remain tied to message IDs

Edit logic must be idempotent.

## 6. Archive deletion/integrity reconciliation

Bot API has no channel-message deletion update.

Implement an operational audit command rather than pretending deletion is live:

`python -m cinegate.ops archive verify`

Initial verification scope:

- inspect indexed poster + quality Archive message references in bounded batches through the authorized Telethon operational session
- mark/report missing references
- do not automatically delete catalog rows unless an explicit repair action is requested
- produce owner/actionable summary
- preserve normal service separation; UserBot is not permanent

A later explicit `repair` mode may be added only with its own plan/approval if destructive behavior is needed.

## 7. Backup/restore

Add provider-neutral PostgreSQL backup/restore runbook.

Requirements:

- `pg_dump` custom-format backup
- credentials not exposed in shell history/process command when avoidable
- timestamped backup filename
- backup directory permissions guidance
- restore into a fresh database first
- run Alembic verification after restore
- smoke/readiness test after restore
- document media is not backed up by DB because Telegram Archive is media source of truth

Automated tests should validate command/config construction where practical. Real destructive restore is not run against user production data in CI.

## 8. Deployment/runbook

Provider-neutral deployment assumptions:

- PostgreSQL persistent volume/service
- CineGate app bound to localhost/private interface
- trusted HTTPS reverse proxy/tunnel in front
- raw access logging configured not to leak secret callback path
- systemd or equivalent service manager
- restart policy
- environment file permissions
- migrations before application start
- readiness check after start
- webhook set/status after HTTPS URL is live
- `max_connections=1`

Do not bind a production management/debug surface publicly without authentication.

## 9. Startup validation

Fail fast for impossible bootstrap configurations.

Validate:

- required secrets
- DB driver
- owner ID if configured
- webhook secret syntax
- public_base_url HTTPS when webhook ops run
- archive/source IDs differ where relevant

Normal service may start before AdsGram/public URL is configured; those are feature readiness, not process liveness.

## 10. Load/race/restart testing

Add deterministic tests for:

- search limiter under rapid messages
- callback limiter
- limiter key eviction/expiry
- reward HTTP limiter + Retry-After
- readiness DB failure
- readiness worker failure
- sanitized logging
- webhook command expected config
- edited Archive post idempotency
- restart worker/readiness
- rapid concurrent search/callback regression
- historical/import unaffected by public-user limiter

No synthetic benchmark result may be presented as production capacity unless measured in a real deployment.

## Review #1 — correctness/security

Review:

- no secret in logs
- rate limiting cannot become correctness dependency
- provider callback not blocked by user limiter
- admin/archive ingestion unaffected by public abuse limiter
- webhook ops never print bot/secret values
- edited Archive updates cannot corrupt valid references
- integrity audit is read-only by default
- backup docs do not encourage secret exposure
- readiness does not require external services

## Review #2 — performance/complexity

Review:

- limiter memory is bounded
- expired keys cleaned incrementally
- logging serialization is lightweight
- no request-body logging
- readiness DB query is minimal
- edited post reparse is bounded/local
- integrity audit batches references
- no Redis/broker/new daemon without evidence
- operational CLIs do not affect long-running service

## Acceptance criteria

- [x] public-user abuse limits implemented and tested
- [x] reward claim HTTP rate limit returns 429 safely
- [x] structured logging redacts sensitive routes/data
- [x] liveness/readiness implemented
- [x] webhook set/status/delete tooling implemented
- [x] webhook operations enforce max_connections=1
- [x] real-time edited_channel_post reconciliation implemented
- [x] Archive deletion limitation documented honestly
- [x] read-only Archive integrity audit implemented
- [x] backup/restore runbook added
- [x] deployment/runbook added
- [x] final launch checklist added
- [x] full CI passes
- [x] two reviews documented
- [x] project memory/status/roadmap/progress updated

## Implementation steps

- [x] 1. Create this plan before code.
- [x] 2. Implement bounded public-user rate limiter.
- [x] 3. Wire Telegram message/callback limits.
- [x] 4. Wire HTTP reward claim limit.
- [x] 5. Add structured/redacted logging.
- [x] 6. Add readiness endpoint and runtime health state.
- [x] 7. Add webhook operations CLI.
- [x] 8. Add edited_channel_post reconciliation.
- [x] 9. Add Archive integrity audit command.
- [x] 10. Add backup/restore runbook.
- [x] 11. Add deployment runbook/service template.
- [x] 12. Add launch checklist.
- [x] 13. Add hardening tests.
- [x] 14. Run full CI.
- [x] 15. Correctness/security review.
- [x] 16. Performance/complexity review.
- [x] 17. Final CI.
- [x] 18. Update repository memory/docs.
- [x] 19. Mark complete.

## Progress notes

### 2026-09-21

- Plan created before implementation.
- Bot API 10.3 Update capabilities reviewed.
- `edited_channel_post` is available through Bot API.
- channel-message deletion updates are not exposed through Bot API; deletion audit will therefore be operational/read-only rather than falsely described as real-time.
- Added bounded search/callback/reward-claim rate limiting; the limiter is deliberately not a correctness primitive.
- Added structured JSON request/application logs, secret-path redaction, `/readyz`, worker/database readiness, and a bounded database-readiness timeout.
- Added safe webhook set/status/delete operations with explicit allowed updates and `max_connections=1`.
- Added idempotent Archive edit reconciliation and a read-only, batched, high-watermark-bounded Archive reference audit.
- Added executable atomic backup/restore scripts, provider-neutral deployment guidance, a hardened single-process systemd template, and the launch checklist.
- The first continuation CI exposed a missing restore transaction flag; production code was corrected with `--single-transaction` instead of weakening the test.
- A later CI exposed stale SQLAlchemy aggregate state during quality repair; production now flushes pending edits before status recomputation.

### Correctness/security review

Found and fixed:

- invalid or conflicting Archive quality edits can no longer be reactivated by a stale duplicate or a different valid quality update
- Archive edit/ingest locking now consistently acquires movie before quality, avoiding the inverse-lock deadlock window
- rewarded delivery remains bound to the exact quality row and refuses changed/unsafe Archive metadata
- AdsGram callback paths remain redacted even for trailing-slash/extra-path requests
- unexpected operations CLI errors expose only the exception class, not secret-bearing payloads
- runtime, Bot, database, and operational resources are released on failure paths
- restore validates the archive and runs atomically; backup publication is atomic and removes failed partial files

### Performance/complexity review

Confirmed/fixed:

- limiter key/deque growth is bounded and repeated blocked-search notices are throttled
- rate limiting remains single-process protection only; PostgreSQL state machines retain correctness
- readiness uses one `SELECT 1`, has a bounded timeout, and does not call Telegram/AdsGram
- Archive edits reparse only the affected message/group
- integrity audit performs bounded Telegram batches against start high-watermarks, so concurrent catalog growth cannot make a run unbounded
- Telegram/network calls remain outside long database transactions
- Telethon remains optional and lazy-loaded only for the audit/import tools
- no Redis, broker, additional daemon, or new dependency was added

### Final verification

GitHub Actions run `35613474434` on commit `09e9d3abce58fb9b833b01b408aa0f6e81d6d4df`:

- Ruff: passed
- pytest: **285 passed**
- PostgreSQL migrations `0001 → 0010`: passed
- full downgrade to base and restore to head: passed
- compileall: passed
- shell-script syntax checks: passed

## Completion summary

Plan 0009 is complete.

Remaining work is external launch execution rather than missing implementation:

- choose/configure the production host and trusted HTTPS edge
- provide production Telegram/AdsGram values
- perform a restore drill against a fresh non-production database
- execute the controlled live Telegram/AdsGram checklist
- configure external monitoring/alert delivery

The exact next step is to deploy the verified `main` revision in the chosen production environment and work through `docs/LAUNCH_CHECKLIST.md`. Keep webhook concurrency at `max_connections=1`.
