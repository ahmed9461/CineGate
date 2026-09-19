# CineGate Decision Log

Record durable decisions here. If a decision changes, do not silently delete the old one; mark it superseded and add the new decision.

## D-001 — Archive Channel is the media source of truth

**Status:** Accepted  
**Date:** 2026-09-19

CineGate will use a dedicated private Telegram Archive Channel as the source for movie poster/info posts and quality files.

**Reason:** The owner already has the required content in Telegram and does not need external movie metadata services for normal operation.

---

## D-002 — No external movie lookup for normal search/display

**Status:** Accepted  
**Date:** 2026-09-19

Poster, information, and available qualities come from the archive/index. Search is against the local CineGate catalog.

---

## D-003 — Search is direct English text with typo tolerance

**Status:** Accepted  
**Date:** 2026-09-19

Users type the English movie name directly. No dedicated search button is required. Reasonable misspellings should yield the closest relevant candidates.

---

## D-004 — Runtime settings in persistent storage; environment for secrets

**Status:** Accepted  
**Date:** 2026-09-19

Routine configuration and user-facing message templates should be editable from the owner bot and persist without requiring source edits. Environment configuration is reserved for secrets/sensitive bootstrap values.

---

## D-005 — Movie delivery expiration is durable

**Status:** Accepted  
**Date:** 2026-09-19

Auto-deletion may not depend only on an in-memory timer. Delivery/deletion deadlines are persisted and reconciled after restart.

---

## D-006 — Poster is not deleted by movie-file expiration

**Status:** Accepted  
**Date:** 2026-09-19

Only the delivered quality/file message is subject to the configured timer.

---

## D-007 — One-time UserBot import; ongoing archive submission by owner

**Status:** Accepted  
**Date:** 2026-09-19

For historical migration, owner may temporarily disable forwarding restriction and use a UserBot to populate the Archive Channel. For future additions, owner sends content to the Archive Channel and CineGate indexes it.

---

## D-008 — Reward verification precedes delivery

**Status:** Accepted  
**Date:** 2026-09-19

Selecting a quality creates a reward session. The movie is delivered only after verified rewarded-ad completion.

---

## D-009 — Plan-first repository workflow is mandatory

**Status:** Accepted  
**Date:** 2026-09-19

Every new feature/fix/refactor/migration/integration/investigation starts with a plan file. Important progress must be written back to repository memory/status/logs.

---

## D-010 — Telegram formatting is a first-class requirement

**Status:** Accepted  
**Date:** 2026-09-19

CineGate should deliberately preserve/use Telegram formatting, rich-message capabilities where appropriate, RTL, and supported button styling rather than reducing everything to plain text.

---

# Pending decisions

- Exact archive grouping/parser format
- Backend/bot framework
- Database
- Ad provider
- UserBot implementation library
- Hosting/deployment model
- Telegram Bot API/client library versions
