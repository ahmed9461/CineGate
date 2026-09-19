# Plan 0002 — Archive format and parser specification

**Status:** Completed  
**Created:** 2026-09-19  
**Last updated:** 2026-09-19

## Objective

Define a deterministic, production-safe parser specification for CineGate that can index the owner's real Telegram archive format and associate each poster/info post with the quality media messages that belong to it.

The parser must support both the current modern posting style and the older legacy style without depending on exact title equality.

## Context

The owner provided real examples from the movie channel and confirmed two historical formats.

### Modern/current format

Poster/info post typically contains structured fields such as:

- `الفيلم:`
- `التصنيف:` / `النوع:`
- `البلد:`
- `اللغة:`
- `الترجمة:`
- `الجودة:`
- `السنة:`
- `التقييم:`
- `القصة:`

One or more video posts follow the poster. Their captions normally contain the movie name and a quality marker such as:

- `#480p`
- `#720p`
- `#1080p`

### Legacy format

Poster/info post may contain:

- `#طلب_المتابعين` (optional)
- title-label variants:
  - `فيلم`
  - `فلم`
  - `الفيلم`
  - `الفلم`
- other info fields such as type, language, country, translation, story

Quality video captions normally contain:

- movie title
- quality
- bot username or other noise text

### Confirmed real inconsistencies

The parser must tolerate:

- `&` in one caption and `and` in another
- punctuation such as `:` being present in one place and absent in another
- slightly different wording/spelling
- poster title and quality-caption title occasionally being in different languages
- historical noise text and bot usernames
- poster posts with no following quality media

The owner confirmed that the poster is followed by one, two, three, or four quality videos depending on available qualities.

## Inputs / evidence

- Real screenshots/examples supplied by the owner on 2026-09-19
- `PROJECT_MEMORY.md`
- `PROJECT_STATUS.md`
- `docs/PRODUCT_SPEC.md`
- `docs/DECISIONS.md`

## Scope

### In scope

- poster candidate rules
- quality candidate rules
- modern parser rules
- legacy parser rules
- sequence-based grouping
- title normalization
- confidence/ambiguity handling
- orphan-poster handling
- duplicate-quality handling requirements
- parser state-machine specification
- test-fixture requirements

### Out of scope

- production parser code
- database migration implementation
- Telegram ingestion implementation
- UserBot migration implementation
- rewarded ads
- delivery and auto-deletion implementation

## Confirmed requirements

- [x] Archive Channel is the source of truth.
- [x] Modern format is the primary/current path.
- [x] Legacy format is supported for historical compatibility.
- [x] Grouping is sequence-first, not exact-title-first.
- [x] Title matching is a supporting signal only.
- [x] A poster with zero valid quality messages must not enter the searchable catalog.
- [x] Incorrect attachment is worse than safely flagging/skipping an ambiguous group.
- [x] Original raw captions must remain available for diagnostics.
- [x] Quality availability is derived from actual quality/media posts, not only a poster's informational `الجودة:` field.

## Parser model

Use a state machine with two main states:

1. `WAITING_FOR_POSTER`
2. `COLLECTING_QUALITIES`

### WAITING_FOR_POSTER

Scan messages until a valid poster candidate is found.

When found:

- classify parser style: modern or legacy
- extract poster title and metadata
- keep raw caption
- open an in-memory movie group
- switch to `COLLECTING_QUALITIES`

### COLLECTING_QUALITIES

Read subsequent messages in channel order.

- Valid quality media → attach to current group.
- New poster candidate → close current group, then open a new group.
- End of stream/batch → close current group.
- Limited noise may be tolerated by the implementation only when validated by tests.
- Excessive/unrelated interruption must not cause forced attachment.

### Closing a group

If accepted quality count is at least 1:

- group may become `indexed`

If accepted quality count is 0:

- group becomes `orphan`
- it is not searchable

If evidence is contradictory or unsafe:

- group becomes `ambiguous`
- it is not searchable until resolved

## Poster detection

### Modern poster candidate

Strong signals:

- poster/photo-like media
- structured movie metadata
- `الفيلم:` is a particularly strong title indicator
- supporting fields such as:
  - `التصنيف:`
  - `النوع:`
  - `البلد:`
  - `اللغة:`
  - `الترجمة:`
  - `السنة:`
  - `التقييم:`
  - `القصة:`

A modern poster does not require every field.

### Legacy poster candidate

Signals include:

- poster/photo-like media
- title-label variants:
  - `فيلم`
  - `فلم`
  - `الفيلم`
  - `الفلم`
- optional `#طلب_المتابعين`
- supporting metadata such as:
  - `النوع`
  - `اللغة`
  - `البلد`
  - `الترجمة`
  - `القصة`

`#طلب_المتابعين` increases confidence but is not mandatory.

## Quality detection

A quality candidate must be movie media intended for delivery (video or compatible media/document representation) and should expose a supported quality marker.

Initial normalized quality keys:

- `480p`
- `720p`
- `1080p`
- `2160p`
- `4k`

Hashtag and plain forms are accepted.

Examples:

- `Irish Ashes 2025 #480p`
- `The twon 2010` + `الجودة: 720p`

Release/source labels such as `WEB-DL`, `WEBRip`, or `BluRay` are metadata, not automatically treated as the delivery-resolution key.

## Sequence-first grouping rule

The strongest link between a poster and the following qualities is message order.

Once a valid poster opens a group, subsequent quality media are presumed to belong to that group until a new poster boundary appears, subject to safety checks.

This deliberately handles cases where:

- poster title uses `&` and video uses `and`
- punctuation differs
- title spelling varies slightly
- poster title language differs from the quality caption language

Exact literal equality is never required.

## Title normalization

Keep both raw title and normalized title.

Normalization should at minimum:

1. Unicode-normalize text.
2. lowercase Latin text.
3. trim and collapse whitespace.
4. normalize punctuation/separators.
5. treat `&` and `and` as equivalent for comparison.
6. separate year from title when reliably detected.
7. separate quality token from title when reliably detected.
8. remove known structural/noise tokens only when safe:
   - `فيلم`
   - `فلم`
   - `الفيلم`
   - `الفلم`
   - `الجودة`
   - `quality`
   - known bot-username noise
9. never destroy the original caption/title.

Do not transliterate/translate titles automatically as a hard dependency. Sequence is what allows cross-language poster/video grouping.

## Compatibility and confidence signals

The implementation should use a confidence model rather than one brittle equality check.

Positive signals:

- direct adjacency / short sequence distance
- valid quality extraction
- matching year
- strong normalized-title similarity
- expected modern/legacy caption structure

Negative signals:

- obvious conflicting year
- clearly unrelated title where sequence evidence is weak
- long unrelated interruption
- contradictory media semantics

Exact numeric weights are intentionally deferred to implementation/testing.

## Group outcomes

### indexed

- valid poster
- at least one accepted quality
- safe enough to expose in search

### orphan

- valid poster
- no accepted following quality
- retained only for diagnostics if useful
- never exposed in search

### ambiguous

- possible movie group, but unsafe to link automatically
- excluded from search until resolved/reprocessed

### ignored

- irrelevant/non-movie/noise message

## Canonical title behavior

For structured modern posters:

- poster title is the preferred canonical/display title

For legacy posters:

- best extracted poster title is preferred when reliable

Quality-caption titles should be retained as secondary evidence and may later become search aliases if a dedicated plan approves that behavior.

## Duplicate handling requirements

Implementation must be idempotent.

Reprocessing the same archive messages must not duplicate:

- movie groups
- quality rows
- archive references

If the same quality appears twice for the same group, implementation must resolve it deterministically and record enough information for diagnosis.

## Data/schema expectations

Conceptually, implementation will need entities similar to:

### movies / movie_groups

- id
- archive poster message id
- raw title
- normalized title
- display title
- year
- parser style (`modern` / `legacy`)
- status (`indexed` / `orphan` / `ambiguous`)
- raw poster caption
- confidence / diagnostic metadata

### movie_qualities

- id
- movie id
- archive quality message id
- normalized quality
- raw caption
- extracted title/year
- confidence / diagnostic metadata

Final schema is deferred to the application-foundation/database plan.

## Security / abuse

- captions are data, never executable input
- no `eval` / shell execution
- parameterized database operations
- bounded regex/input processing
- avoid catastrophic regex behavior
- malformed captions must fail safely

## Failure / recovery cases to test

- [x] modern poster + one quality
- [x] modern poster + multiple qualities
- [x] legacy poster + one/multiple qualities
- [x] poster with zero qualities → orphan
- [x] `&` vs `and`
- [x] colon/punctuation differences
- [x] cross-language poster/video title
- [x] quality message without poster
- [x] poster immediately followed by another poster
- [x] duplicate quality
- [x] repeated import/re-index
- [x] unrelated/noise message
- [x] interrupted batch/restart requirement documented

These are specification cases; executable fixtures/tests are required in the later implementation plan.

## Acceptance criteria

- [x] Real modern posting style is documented.
- [x] Real legacy posting style is documented.
- [x] Poster and quality candidate rules are defined.
- [x] Sequence-first grouping is the primary rule.
- [x] Exact title equality is explicitly rejected as a requirement.
- [x] Normalization behavior is defined.
- [x] Orphan/ambiguous behavior is defined.
- [x] Duplicate/idempotency requirements are defined.
- [x] Implementation test cases are enumerated.
- [x] No production parser code was started before this plan/specification existed.

## Documentation updates

- [x] `PROJECT_MEMORY.md`
- [x] `PROJECT_STATUS.md`
- [x] `docs/PROGRESS_LOG.md`
- [x] `docs/DECISIONS.md`
- [x] `docs/PRODUCT_SPEC.md`
- [x] `ROADMAP.md`

## Completion summary

The real archive structure is now documented and the parser strategy is fixed at the specification level.

**Key decision:** CineGate groups by sequence first, then uses normalized title/year/quality evidence as supporting confidence signals.

**Next exact step:** create the next plan before writing application code. That plan must select the application stack/database/service boundaries and convert this parser specification into executable fixtures, schema, and implementation tasks.
