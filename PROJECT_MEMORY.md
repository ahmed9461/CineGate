# CineGate Project Memory

**Last updated:** 2026-09-19  
**Purpose:** Durable source of project context so work can resume without relying on chat history.

---

## 1. Product summary

CineGate is a separate Telegram bot for searching movies and delivering an available quality after the user completes a rewarded advertisement.

The project does **not** need an external movie database for posters, movie metadata, or quality availability. The Telegram archive is the content source.

---

## 2. Confirmed user flow

1. User opens the bot.
2. User directly types the movie name in English.
3. No dedicated “Search” button is required.
4. Bot searches the local movie index.
5. Search should tolerate reasonable English spelling mistakes.
6. If several close results exist, bot shows them as buttons.
7. User selects a movie.
8. Previous result UI may be removed/replaced as appropriate.
9. Bot copies/sends the movie poster + original information from the archive channel.
10. Under the poster, bot shows only qualities actually available for that movie, e.g.:
    - 480p
    - 720p
    - 1080p
    - Back
11. User chooses a quality.
12. Bot explains that one short advertisement must be completed before receiving that quality.
13. “Watch ad” opens a Telegram Mini App / rewarded-ad flow.
14. Delivery is unlocked only after verified ad completion.
15. Bot copies the selected quality from the archive channel to the user.
16. The delivered movie message gets a configurable caption/template.
17. After a configurable duration, the **movie file message** is automatically deleted from the user’s chat with the bot.
18. The poster/information message is not deleted by this timer.

---

## 3. Archive model

### Original channel

- Owner already has a private original movie channel.
- Original channel may have Telegram content-forwarding/saving restriction enabled.
- CineGate must not rely on bypassing Telegram content protection.

### Initial migration

- For the one-time initial import, owner will temporarily disable the original channel’s forwarding restriction.
- A Telegram UserBot may then copy/forward historical movie posts into the dedicated CineGate Archive Channel.
- After initial migration, the protection on the original channel can be re-enabled.

### Archive Channel

- A separate private Telegram channel is used as CineGate’s storage/archive.
- CineGate bot is an administrator in the archive channel as needed.
- Archive Channel is the source of truth for:
  - poster/information post
  - movie quality messages/files
  - Telegram message references required for delivery

### Ongoing updates

After the initial migration:

- Owner will also send new movie content to the Archive Channel.
- CineGate indexes new archive posts automatically.
- Owner receives a summary notification after successful indexing, conceptually:

```
تم حفظ منشورات جديدة

1- Interstellar (3)
```

Meaning the movie was saved with three associated qualities.

If multiple movies are indexed together, notification may summarize all of them.

### Pending archive detail

**The exact real-world post structure has not been provided yet.**

Do not implement the final archive parser until sample poster + quality posts are supplied and documented.

The parser must be designed around the owner’s actual channel format rather than forcing a new publishing format without approval.

---

## 4. Search behavior

Confirmed:

- English movie titles only.
- No Arabic title search requirement.
- User types text directly.
- No required search-mode button.
- Prefer relevant exact/near matches before fuzzy matches.
- Support reasonable spelling mistakes.
- Show multiple close candidates as Telegram buttons.
- No-result message is owner-editable.

Current desired default no-result copy:

```
عذرا لم أجد نتائج بحث ‼️

هذا يعني اما الفيلم غير متوفر في ذاكرتي او ان نص البحث غير دقيق ، حاول كتابة الاسم الصحيح و اذا مازالت تظهر هذه الرسالة ف هذا يعني ان الفيلم غير متوفر.
```

Final wording remains editable from the bot.

Security requirements:

- Treat user search text strictly as data.
- Parameterized database queries.
- No eval/shell execution from user input.
- Input length limits.
- Rate limiting / abuse protection.
- Safe normalization and fuzzy matching.

---

## 5. Rewarded advertisements

- A selected quality requires completion of one rewarded advertisement before delivery.
- Ad provider/network is **not finalized yet**.
- Provider must allow rewarded/incentivized traffic and provide a reliable completion/reward signal suitable for server-side verification.
- Do not unlock delivery merely because the Mini App was opened.
- A reward session must bind at minimum:
  - Telegram user
  - movie
  - selected quality
  - archive message reference
  - reward status
  - timestamps
- One reward must not be reusable to unlock unrelated qualities.
- If reward succeeds but delivery temporarily fails, system should preserve rewarded state so the user is not unfairly forced to watch another ad for the same pending delivery.

---

## 6. Temporary delivery and deletion

Owner can configure movie deletion timing from inside the bot.

Example delivery caption:

```
Top Gun 1986 720p

مهم جدا
يرجى تحويل الفيديو الى رسائل المحفوظة او اي محادثة اخرى لانه سوف يتم حذفه بعد %time%
```

Required template variables include at least:

- `%movie%`
- `%year%`
- `%quality%`
- `%time%`

Additional useful variables may be added after planning, such as `%seconds%` or `%expires_at%`.

Important behavior:

- Changing deletion duration should not require editing the entire message template.
- `%time%` resolves dynamically.
- Only the delivered movie/file message is automatically deleted.
- Poster/info stays.
- Deletion must survive application restart.
- Do not rely only on in-memory sleep timers.
- Persist deletion jobs / delivery expiry data.
- On restart, reconcile overdue or pending deletions.

---

## 7. Owner/admin configuration

Strong requirement: **normal settings must be manageable from inside the bot.**

Examples:

- deletion duration
- message templates
- search result count
- fuzzy-match behavior/thresholds where appropriate
- archive/indexing notifications
- advertisement configuration that is not secret
- enable/disable applicable features
- button presentation/style
- other runtime behavior

Changing normal settings should not require:

- editing source code
- editing `.env`
- restarting the whole project unnecessarily

`.env` is reserved for secrets and sensitive bootstrap configuration.

---

## 8. Editable messages and variables

Bot-facing messages should be stored as editable templates rather than scattered hard-coded strings.

Expected template categories include:

- welcome/start
- search results
- no results
- movie selection
- watch advertisement
- ad failure
- ad success
- delivery caption
- generic error
- archive indexing owner notification

Templates should expose documented variables and validate unsupported variables before saving where practical.

---

## 9. Telegram presentation requirements

CineGate should intentionally support Telegram’s modern formatting capabilities rather than flattening everything to plain text.

Requirements include:

- Telegram message entities / formatting
- rich-message compatibility where applicable
- RTL handling for Arabic owner/user messages
- modern Telegram button styling where supported
- owner-editable messages should preserve supported formatting
- button creation should be centralized so presentation changes are consistent

Exact Bot API feature usage must be validated against the Bot API version/library selected during implementation.

---

## 10. Data/source-of-truth principle

Media should remain in Telegram.

Application database should primarily store metadata/indexes/references such as:

- movie identity
- normalized/search title
- year when available
- poster archive message reference
- quality
- quality archive message reference
- archive grouping/index state
- reward sessions
- deliveries
- deletion deadlines
- templates/settings
- audit/progress data as needed

Avoid downloading/re-uploading large movie files through the application server when Telegram-side copying can be used safely.

---

## 11. Reliability expectations

Plan for:

- duplicate archive events
- idempotent indexing
- duplicate reward callbacks
- duplicate delivery attempts
- application restart
- database restart
- Telegram temporary errors
- advertisement provider temporary errors
- failed deletion retry/reconciliation
- clear owner-visible errors/logging

---

## 12. Project governance

Every new work item must have a written plan in `plans/` before implementation.

Project memory, current status, active plan, progress log, and decisions must be updated continuously so we always know:

- what happened
- what changed
- what was added
- what failed
- where work stopped
- what remains
- exact next step

See `AGENTS.md`.

---

## 13. Pending decisions / information

Do not guess these:

1. Exact archive post structure linking poster to 480p/720p/1080p/etc.
2. Exact parsing rules — wait for real examples.
3. Rewarded-ad network/provider.
4. Final application technology stack and deployment topology.
5. Final database choice.
6. Initial-import UserBot library/implementation.
7. Final owner/admin menu layout.
8. Exact Telegram Bot API/library versions.

These should be resolved through explicit plans and recorded in `docs/DECISIONS.md`.
