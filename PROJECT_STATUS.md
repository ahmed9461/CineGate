# CineGate Project Status

**Last updated:** 2026-09-19  
**Overall status:** 🟡 Planning / foundation  
**Code status:** No application code implemented yet.

## Completed

- Repository created as `CineGate`.
- Persistent project-memory workflow established.
- Mandatory plan-before-work rule established.
- Core product requirements recorded.
- Initial roadmap recorded.
- Progress/decision tracking structure created.
- Secret/session files protected through `.gitignore`.

## Current checkpoint

We have defined the product flow and archive strategy, but the archive parser must **not** be implemented yet because the owner has not yet supplied the real movie post structure.

## Next exact step

1. Owner provides real examples/screenshots/text structure showing:
   - poster/information post
   - each quality post/file
   - ordering/grouping between films
   - any captions/labels used
2. Create `plans/0002-archive-format-and-parser.md`.
3. Document deterministic grouping/parsing rules.
4. Validate edge cases with the owner-provided examples.
5. Only after that, implement the archive indexer/parser.

## Open decisions

- [ ] Exact archive post/group structure
- [ ] Rewarded-ad provider
- [ ] Final backend/bot technology stack
- [ ] Database choice
- [ ] UserBot library for one-time initial import
- [ ] Deployment target/topology
- [ ] Exact Bot API/library versions

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
- Every new work item starts with a plan file and ends with memory/status/progress updates.

## Active plan

`plans/0001-project-foundation.md` — **Completed**

## Blockers

No implementation blocker other than intentionally waiting for the archive post format before designing the parser.

## Resume instruction

If resuming after a gap, read `AGENTS.md` first, then this file and `PROJECT_MEMORY.md`. Do not infer missing state from memory or chat alone.
