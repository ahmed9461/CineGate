# CineGate Project Status

**Last updated:** 2026-09-19  
**Overall status:** 🟡 Planning / archive parser specification complete  
**Code status:** No application code implemented yet.

## Completed

- Repository created as `CineGate`.
- Persistent project-memory workflow established.
- Mandatory plan-before-work rule established.
- Core product requirements recorded.
- Initial roadmap recorded.
- Progress/decision tracking structure created.
- Secret/session files protected through `.gitignore`.
- Real archive posting examples received from the owner.
- Modern/current archive format documented.
- Legacy/historical archive format documented.
- Sequence-first parser/grouping strategy specified.
- Title normalization and orphan/ambiguous handling specified.
- `plans/0002-archive-format-and-parser.md` completed.

## Current checkpoint

The archive format is no longer unknown.

CineGate must support:

1. the modern/current structured poster + quality-caption format
2. the older legacy format with optional `#طلب_المتابعين` and title-label variants

The core parser rule is:

**sequence first → normalization/year/title evidence second → ambiguity safety checks**

Exact title equality is not required.

No production parser code has started yet.

## Next exact step

Before application code:

1. Create the next plan for application foundation / parser implementation.
2. Select the bot/backend stack and database.
3. Define service boundaries and persistent schema.
4. Convert Plan 0002 cases into executable parser fixtures/tests.
5. Implement the parser only after that plan is written.

## Open decisions

- [ ] Rewarded-ad provider
- [ ] Final backend/bot technology stack
- [ ] Database choice
- [ ] UserBot library for one-time initial import
- [ ] Deployment target/topology
- [ ] Exact Bot API/library versions
- [ ] Real-time handling for archive post edits/deletes

## Known non-negotiable requirements

- Archive Channel is the media source of truth.
- No external movie lookup is required for posters/info/qualities.
- English direct-text search with typo tolerance.
- Reward verification before quality delivery.
- Configurable temporary movie delivery with durable auto-deletion.
- Poster message is not deleted by the file timer.
- Runtime settings/messages editable in the owner bot.
- Environment files reserved for secrets/bootstrap sensitive values.
- Telegram formatting/rich presentation must be preserved intentionally.
- Modern archive style is the primary ingestion format.
- Legacy archive style must remain compatible for historical import.
- Archive grouping is sequence-first, not exact-title-first.
- A poster with zero valid qualities is not searchable.
- Ambiguous attachment is safer than a wrong automatic association.
- Every new work item starts with a plan file and ends with memory/status/progress updates.

## Active plan

`plans/0002-archive-format-and-parser.md` — **Completed**

## Blockers

No blocker. The next work item must receive its own plan before any implementation begins.

## Resume instruction

If resuming after a gap, read `AGENTS.md`, `PROJECT_MEMORY.md`, this file, and `plans/0002-archive-format-and-parser.md` before starting new work.
