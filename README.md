# actiontrack

Reads meeting-note markdown files, tracks the action items in SQLite, and drafts follow-up emails
(drafts only, never sends). Python 3.10+, no runtime dependencies.

```
python -m actiontrack ingest notes/
python -m actiontrack list --status overdue
python -m actiontrack list --owner "Priya Nair" --due-before 2026-10-20
python -m actiontrack done 12
python -m actiontrack followup "Sam Okafor" --dry-run
python -m actiontrack followup --all --eml
```

(`pip install -e .` also gives you an `actiontrack` command.) Full behaviour: [docs/SPEC.md](docs/SPEC.md).

## Commands

| Command | What it does |
|---|---|
| `ingest <folder>` | Parses every `.md` note; prints files skipped (with reason), items added/merged, and warnings. Safe to re-run. |
| `list` | `--owner NAME`, `--status open\|done\|overdue`, `--due-before YYYY-MM-DD`. Status: `done`; `overdue` = not done and due before today; `open` = everything else not done. |
| `done <id>` | Marks an item done. Sticky: re-ingesting never reopens it. |
| `followup <owner>` / `--all` | One email per owner with open + overdue items (overdue first). Creates a Gmail draft. |

Global options: `--db PATH` (default `actiontrack.db`, env `ACTIONTRACK_DB`), `--today YYYY-MM-DD`
(default: system date, env `ACTIONTRACK_TODAY`). Useful because the sample notes are from 2026.

## Follow-up emails and Gmail

- Recipients come from `people.json` (`{"Full Name": "email"}`). No entry → draft without recipient, with a warning.
- `--dry-run` prints the email. `--eml` writes `drafts/<name>.eml`.
- Default mode creates a **Gmail draft through the Gmail MCP connector**. A plain CLI can't speak to a
  claude.ai connector itself, so it runs headless Claude Code (`claude -p`) with `--allowedTools` limited to
  the single create-draft tool (`mcp__claude_ai_Gmail__create_draft`, override via `ACTIONTRACK_GMAIL_TOOL`).
  No send tool is ever allowed. Requires the `claude` CLI on PATH with the Gmail connector authorised.
- If that fails, the tool says so on stderr, saves the `.eml` fallback, and exits with code 3.

Exit codes: 0 ok, 1 unknown id, 2 usage/bad input, 3 Gmail draft not created.

## How it handles the awkward cases

- **Duplicates**: same owner + similar task text (fuzzy) = one item with several source meetings; status and due date come from the latest meeting.
- **Same first name** (two Priyas, two Rahuls): resolved by full name / initial (`Priya N.`) or by the meeting's attendee list. If still unclear the item is shown as `Priya?`, reported at ingest, and never guessed. `list --owner Priya` shows both Priyas plus the ambiguous ones.
- **No owner / group owner** (`Everyone`, `Team`, `TBD`, `Someone`): kept, shown as `(everyone)` etc.
- **No due date**: kept, never overdue. Relative dates ("by Friday", "next Tuesday", "end of next week", "mid-October") resolve against the meeting date.
- **Malformed notes** (no/invalid date, binary): skipped and listed. Non-`.md` files are ignored.
- Task-like lines inside code fences, HTML comments and `>` quotes are not action items.

## Tests

```
python -m pytest -q
```
Unit tests plus end-to-end tests over `notes/` (35 files: 3 skipped as malformed, 1 `.txt` ignored). Gmail is mocked.
# evaluation_project
