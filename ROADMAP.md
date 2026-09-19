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

- [ ] Direct text search
- [ ] English normalization
- [ ] Exact/prefix/word ranking
- [ ] Typo-tolerant fuzzy ranking
- [ ] Relevance thresholds
- [ ] Result buttons
- [ ] No-result template
- [ ] Input/rate-limit protections
- [ ] Search metrics/debugging

## Phase 5 — Movie page & quality selection

- [ ] Copy/send archive poster/info
- [ ] Render only available qualities
- [ ] Back/results navigation
- [ ] Stale/deleted archive-reference handling
- [ ] Centralized button rendering/styles

## Phase 6 — Rewarded advertisement flow

- [ ] Choose provider
- [ ] Confirm incentivized/rewarded traffic policy
- [ ] Mini App integration
- [ ] Signed Telegram identity validation
- [ ] Reward session state machine
- [ ] Server-side reward verification/callback
- [ ] Replay/duplicate protection
- [ ] Failure/retry UX
- [ ] Preserve completed reward if delivery temporarily fails

## Phase 7 — Delivery & durable deletion

- [ ] Copy selected archive quality to user
- [ ] Template variable rendering
- [ ] Persist delivery message ID
- [ ] Persist expiration/deletion deadline
- [ ] Durable deletion worker
- [ ] Restart reconciliation
- [ ] Retry failures
- [ ] Ensure poster remains untouched
- [ ] Owner-configurable deletion duration

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
