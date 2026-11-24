# actiontrack — Specification

A small CLI that reads meeting-note markdown files, tracks action items in SQLite, and drafts
follow-up emails (never sends). Python 3.10+, stdlib only.

## 1. Meeting note format (input)

A note is a `.md` file in the ingest folder (top level only; other extensions are ignored).

| Part | Accepted forms |
|---|---|
| Date (required) | `Date: 2026-09-01`, `Date: 9 September 2026`, `Date: Monday, 14 September 2026`, or YAML front matter `date:` |
| Attendees (optional) | `Attendees: A B, C D` or front matter `attendees: [A B, C D]` |
| Items | `- [ ] text`, `* [ ]`, `+ [ ]`, `[x]`/`[X]` = done, nested (indented) bullets, `ACTION: text`, and table rows under an `Owner \| Action \| Due` header |

Never parsed as items: fenced code blocks, HTML comments, blockquote (`>`) lines.

Item text is `<Owner> to <task> [by <due>]`, or `@owner: task`, or a table row. Owner may be a
first name, `Priya N.`, a full name, `A & B` (one item per owner), or a group word
(`Everyone`, `Team`, `Someone`, `TBD`) which means *unassigned*. `(with X)` is ignored.

## 2. Malformed notes (REQ-M)

- M1: no valid `Date` (missing, or unparseable such as "sometime last week") → skip, report reason.
- M2: binary / non-UTF-8 content → skip, report reason.
- M3: no attendees → parse, emit a warning.
- M4: ingest never crashes on a bad file (any parse error is caught per file); the summary lists every
  skipped file with its reason. Short/odd table rows are ignored, not fatal. Subfolders are not scanned (reported).

## 3. Owner resolution (REQ-O)

Known people = every attendee full name seen in any note (persisted in the DB).

- O1: full name or `First L.` initial → matched against known people.
- O2: first name only → candidates are known people with that first name; if the meeting's
  attendees narrow it to exactly one, use it; if exactly one known person exists, use it.
- O3: still more than one candidate → **ambiguous**: owner is left unresolved (`owner_raw` kept),
  flagged and reported. Never guess.
- O4: group words / no owner → unassigned, reported.
- O5: a name that matches nobody is stored as written, **warned as unknown**, and never emailed by `followup --all`.
- O6: the owner text before " to " must look like a name (1-3 capitalised words, or `A, B` / `A & B`) or a group
  word; otherwise the line has no owner (`Review the plan to improve latency` is an ownerless task).
  A single capitalised first word still reads as a name; O5 is the safety net.
- O7: resolution happens at ingest time against the people known *then*; a first name that was unique
  earlier stays attributed to that person even if a namesake shows up in a later ingest.

## 4. Due dates (REQ-D)

Resolved against the meeting date to an ISO date. No due date → none stored (never overdue).

| Phrase | Rule |
|---|---|
| ISO, `10 Sep`, `Oct 3rd`, `Wed 16 Sep`, `15 October` | explicit; year = meeting year (next year if >60 days in the past) |
| `Friday`, `Wed`, `by Mon` | first such weekday on/after the meeting date |
| `Friday next week` | that weekday in the following Mon-Sun week |
| `in 2 weeks`, `in 3 days` | meeting date + N |
| `by the 15th` | next 15th on/after the meeting date |
| `EOW` | same as `end of week` |
| `COB` | same as `EOD` |
| `next Tuesday` | that weekday in the following Mon–Sun week |
| `tomorrow`, `EOD tomorrow` | meeting date + 1 |
| `today`, `EOD` | meeting date |
| `end of (next) week` | Friday of this (next) week |
| `end of month` | last day of the meeting's month |
| `mid-October` | the 15th of that month |
| anything else (`next quarter`) | no due date |

A bare weekday, `today` or `tomorrow` only counts after a cue word (`by`, `before`, `on`, `until`, `due`,
`for`, `this`, `from`) or at the very end of the text, and never when possessive. So `review the Monday
report`, `update today's report` and `prepare for Friday's demo` keep their text and get no date.
The due phrase is removed from the stored task text. Open items with no due date produce an ingest
warning ("no due date for: ...").

## 5. Duplicates (REQ-U)

- U1: items with the same owner key and the same task are one item with many sources (meeting file, date,
  line status, due). "Same task" = normalised content words (lower-case, stop words removed) with >= 75%
  overlap and identical numbers (`PR 12` vs `PR 13`, `Q3` vs `Q4` never merge). Ownerless items merge only
  when identical. Repeated lines inside one note collapse to one (done only if every copy is done).
- U2: item status and due date come from the **latest meeting** (by date, then file name); if
  that meeting has no due date, the latest earlier due date is kept.
- U3: an item marked done with `actiontrack done` is never reopened by ingestion.
- U4: ingest is idempotent: re-running changes nothing. A source is identified by (file, owner + normalised
  task), so flipping a checkbox or editing a due date updates it in place. Lines removed from a note are
  dropped from that note's sources; an item with no sources left is removed unless it was marked done by hand.
- U5: ids are auto-increment integers and never change.

## 6. Commands

Global options (before or after the subcommand): `--db PATH` (default `actiontrack.db`, env
`ACTIONTRACK_DB`), `--today YYYY-MM-DD` (default system date, env `ACTIONTRACK_TODAY`).

### `ingest <folder>`
Parse, store, then print: files read / skipped (with reasons) / ignored non-md, items added /
merged / updated, and warnings (ambiguous owners, unassigned, no due date, no attendees).
Missing folder → exit 2. A bad `--db` path or `ACTIONTRACK_TODAY` → clear error, exit 2. A failing command
rolls back; an ingest is never half-committed.

### `list [--owner NAME] [--status open|done|overdue] [--due-before DATE]`
Table: id, status, owner, due, task, latest source file. Status is derived:
`done`; `overdue` = not done and due < today; `open` = not done and not overdue.
`--owner` matches a full name, or a first name (also matches ambiguous items whose raw owner is
that first name). `--due-before` is strictly before and excludes items with no due date.

### `done <id>`
Marks done (manual, sticky). Unknown id → exit 1. Already done → message, exit 0.

### `followup <owner> | --all  [--dry-run] [--eml] [--people people.json]`
- Owner: full name or first name; ambiguous first name → list matches, exit 2.
- One email per owner: open + overdue items, overdue first, each with due date and source meeting.
- Recipient from `people.json` (`{"Full Name": "email"}`); missing → draft without recipient + warning.
- `--all` only drafts for owners who are known attendees; others are listed as skipped.
- Default: create a Gmail **draft** via the Gmail MCP connector (headless `claude -p`). Hardened: built-in
  tools off (`--tools ""`), `--permission-mode dontAsk`, only the create-draft tool allowed (never a send
  tool), empty temp working directory, note text inside random delimiters, and success only if the last
  output line is exactly `DRAFT_CREATED`.
- `--dry-run`: print the email only. `--eml`: write `drafts/<owner>.eml` only.
- Gmail unavailable/failed → clear error message, `.eml` fallback written, exit 3.
- Ambiguous items that might belong to the owner are mentioned in the console report, not guessed into the email.

## 7. Acceptance

AC1 all four commands work on `notes/` (35 files, 2 malformed `.md`, 1 binary, 1 `.txt`).
AC2 re-ingest is a no-op; `done` survives re-ingest. AC3 no crash on any file in `notes/`.
AC4 two Priyas / two Rahuls are never conflated. AC5 quoted/commented/fenced "tasks" are not ingested.
