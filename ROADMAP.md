# CineGate Roadmap

This roadmap is directional. Every phase requires its own detailed plan file before implementation.

## Phase 0 — Project governance ✅

- [x] Durable project memory
- [x] Current status checkpoint
- [x] Plan-before-work workflow
- [x] Decision log
- [x] Progress log
- [x] Product specification
- [x] Secret/session ignore rules

## Phase 1 — Archive format & parser specification

- [x] Receive real archive/original-channel post samples
- [x] Define poster detection
- [x] Define movie boundary/group detection
- [x] Define quality extraction
- [x] Define title/year extraction and normalization direction
- [x] Define incomplete/ambiguous group handling
- [x] Define duplicate/idempotency requirements
- [ ] Define real-time edit/delete reconciliation behavior
- [x] Implement parser fixtures/tests before production indexing

**Specification:** `plans/0002-archive-format-and-parser.md`  
**Implementation foundation:** `plans/0003-application-foundation-and-parser.md`

## Phase 2 — Application foundation

- [x] Select technology stack
- [x] Select database
- [x] Define service boundaries
- [x] Configuration/secret model
- [x] Database migrations
- [ ] Logging and error model
- [ ] Owner bootstrap/access control
- [x] Basic health/diagnostics

## Phase 3 — Archive indexing & initial import

- [ ] Archive bot permissions
- [x] Archive event ingestion
- [x] Idempotent indexing
- [x] Movie + quality persistence
- [x] Owner “saved posts” notifications
- [ ] One-time UserBot importer
- [ ] Import progress/reporting
- [x] Resume/retry support
- [ ] Large-history validation

**Real-time implementation:** `plans/0004-telegram-webhook-and-archive-indexer.md`

## Phase 4 — Search experience

- [x] Direct text search
- [x] English normalization
- [x] Exact/prefix/word ranking
- [x] Typo-tolerant fuzzy ranking
- [x] Relevance thresholds
- [x] Result buttons
- [x] No-result template
- [ ] Input/rate-limit protections
- [ ] Search metrics/debugging

**Search/movie-page implementation:** `plans/0005-search-and-movie-page.md`

## Phase 5 — Movie page & quality selection

- [x] Copy/send archive poster/info
- [x] Render only available qualities
- [x] Back/results navigation
- [x] Stale/deleted archive-reference handling
- [x] Centralized button rendering/styles

## Phase 6 — Rewarded advertisement flow

- [x] Choose initial provider (AdsGram)
- [x] Confirm rewarded integration model
- [x] Mini App integration
- [x] Signed Telegram identity validation
- [x] Reward session state machine
- [x] Server-side reward verification/callback
- [x] Replay/duplicate protection
- [x] Failure/retry UX
- [x] Preserve completed reward if delivery temporarily fails

## Phase 7 — Delivery & durable deletion

- [x] Copy selected archive quality to user
- [x] Template variable rendering
- [x] Persist delivery message ID
- [x] Persist expiration/deletion deadline
- [x] Durable deletion worker
- [x] Restart reconciliation
- [x] Retry failures
- [x] Ensure poster remains untouched
- [ ] Owner-configurable deletion duration

**Reward/delivery implementation:** `plans/0006-reward-delivery-and-deletion.md`

## Phase 8 — Owner/admin control center

- [ ] Message template editor
- [ ] Preview formatting
- [ ] Runtime settings editor
- [ ] Deletion timing settings
- [ ] Search settings
- [ ] Archive/index notification settings
- [ ] Ad settings (non-secret)
- [ ] Button/presentation settings
- [ ] Audit trail / safe validation
- [ ] Defaults/reset where appropriate

## Phase 9 — Telegram rich presentation

- [ ] Confirm selected library/Bot API support
- [ ] Preserve entities/formatting
- [ ] RTL behavior
- [ ] Rich messages where valuable
- [ ] Modern button styles where supported
- [ ] Fallback behavior for unsupported clients/features

## Phase 10 — Hardening & launch

- [ ] Full automated test suite
- [ ] Abuse/rate-limit tests
- [ ] Duplicate/retry/race tests
- [ ] Restart/recovery tests
- [ ] Security review
- [ ] Performance/load review
- [ ] Backup/restore test
- [ ] Deployment runbook
- [ ] Monitoring/alerts
- [ ] Initial archive migration
- [ ] Production launch checklist
