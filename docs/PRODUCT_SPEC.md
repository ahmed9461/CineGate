# CineGate Product Specification

**Status:** Initial confirmed specification.  
**Last updated:** 2026-09-20

## Goal

Provide a Telegram experience where a user searches an indexed movie catalog, selects an available quality, completes one rewarded advertisement, and receives that movie quality temporarily.

## Primary user journey

### Search

- User sends an English movie title directly into the bot chat.
- Bot searches local indexed archive data.
- Bot should tolerate reasonable misspellings.
- Bot returns closest relevant candidates as buttons when needed.
- Search UI should avoid unnecessary modes/buttons.

### No results

No-result copy is configurable by the owner. Current desired default:

> عذرا لم أجد نتائج بحث ‼️
>
> هذا يعني اما الفيلم غير متوفر في ذاكرتي او ان نص البحث غير دقيق ، حاول كتابة الاسم الصحيح و اذا مازالت تظهر هذه الرسالة ف هذا يعني ان الفيلم غير متوفر.

### Movie selection

After selecting a result:

- previous search-result message can be removed/replaced for a clean flow
- poster + movie information are copied from the Telegram Archive Channel
- only qualities actually indexed for that movie are shown

Example:

```
[480p] [720p]
[1080p]
[رجوع]
```

### Quality selection

After choosing a quality:

- bot creates a reward request bound to that exact user/movie/quality
- user sees an explanation that one short ad must be completed
- button opens rewarded-ad Mini App flow

### Reward

- AdsGram is the initial rewarded-ad integration
- opening the ad page alone is insufficient
- client JavaScript alone is insufficient
- production reward requires Telegram-signed Mini App completion plus AdsGram server Reward URL confirmation
- duplicate callbacks are idempotent
- reward cannot unlock unrelated content
- only one active reward session is allowed per Telegram user because the provider server callback identifies the Telegram user rather than a CineGate session
- provider-only confirmation does not skip the current ad
- earned reward persists through Telegram delivery failure and does not expire with the original ad-session TTL

### Delivery

After verified reward:

- bot copies the requested archive quality to the user
- delivered message uses the owner-configurable delivery-caption template
- delivery is temporary

### Auto-deletion

- owner configures duration from inside the bot
- duration is inserted through `%time%`
- only the delivered movie/file message is deleted automatically
- poster/info is not deleted
- deletion schedule survives service restarts
- overdue/stale delivery states are reconciled during runtime and after restart
- transient failures use bounded retry/backoff
- Telegram's 48-hour deletion window is respected
- permanently impossible deletion is recorded as `delete_failed`, not falsely marked deleted

## Content architecture

### Source of truth

A dedicated private Telegram Archive Channel is the source for movie media and poster/information posts.

No external movie catalog lookup is required for normal operation.

### Initial archive population

Owner temporarily disables content-forwarding restriction in the original private channel, uses the one-time Telethon UserBot importer to transfer historical messages to the Archive Channel, then can re-enable protection.

The importer:

- runs as a separate CLI process
- does not remain active during normal CineGate service operation
- copies/forwards Telegram-side without downloading movie media
- preserves source order
- stores durable source→archive message mapping
- resumes after interruption
- reconciles already-forwarded messages before retrying
- stops safely instead of bypassing protected forwarding
- performs sequential historical reindex after transfer

### Ongoing archive population

Owner sends future movie posts to the Archive Channel as part of normal publishing.

CineGate indexes them and reports successful saved groups to the owner.

### Archive parsing

CineGate supports two real posting styles:

- **Modern/current:** structured poster metadata (for example `الفيلم:`, `السنة:`, `القصة:`) followed by one or more quality media posts with quality markers such as `#480p`, `#720p`, or `#1080p`.
- **Legacy/historical:** older poster metadata that may include `#طلب_المتابعين` and title-label variants such as `فيلم`, `فلم`, `الفيلم`, or `الفلم`, followed by quality media captions that may include extra bot-username/noise text.

Grouping is **sequence-first**. The poster opens a movie group and following quality media are associated with it until a new poster boundary or stream end, subject to safety checks.

Title normalization and similarity help validation but exact title equality is not required. This intentionally tolerates `&` vs `and`, punctuation differences, spelling/format variation, and occasional poster/video title language differences.

A poster with no accepted quality media is not searchable. Unsafe associations are classified as ambiguous rather than force-linked.

See `plans/0002-archive-format-and-parser.md`.

## Owner experience

Routine owner configuration is implemented through an owner-only Telegram control center.

Implemented categories include:

- messages/templates
- deletion duration
- search behavior and result count
- archive/source/notification identifiers
- public Mini App URL and AdsGram Block ID
- reward/session timing
- status and diagnostics
- audit history and reset/default behavior

Sensitive bootstrap values remain environment-only.

Formatted owner messages preserve Telegram entities. Advanced Rich Message authoring and visual button-style customization remain separate future presentation work.

## Template system

At minimum support:

- `%movie%`
- `%year%`
- `%quality%`
- `%time%`

Templates should preserve supported Telegram formatting.

## Telegram UX

Design for:

- Telegram entities/formatting
- Arabic RTL when needed
- Telegram rich-message capabilities where beneficial
- supported modern button styling
- clean navigation
- centralized rendering logic

## Security / abuse

- never execute user search input
- parameterized DB access
- length limits
- rate limiting
- safe Telegram init data validation for Mini App identity
- reward replay protection
- no secrets in DB-exposed admin messages
- no UserBot session material in Git

## Reliability

Must handle safely:

- duplicate archive events
- archive edits
- malformed/incomplete movie groups
- duplicate reward callbacks
- reward success + delivery failure
- bot/backend restarts
- deletion worker restarts
- stale Telegram message references
- Telegram API failures
- ad provider failures
- database failures

## Not finalized

- production AdsGram Block ID/platform/public URL values
- production deployment topology and callback access-log redaction
- real-time archive edit/delete reconciliation behavior
- final Rich Message owner-editor feature set
- durable global webhook sequencing before webhook concurrency is increased

These must be decided through task plans and recorded in the decision log.
