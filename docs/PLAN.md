# actiontrack — Implementation plan

Stdlib only (argparse, sqlite3, email, secrets, subprocess). pytest for tests. No frameworks, no config layers.

| Unit | File | Contents | Tests |
|---|---|---|---|
| U1 Dates | `actiontrack/dates.py` | `parse_meeting_date`, `find_due(text, ref)` | `tests/test_dates.py` |
| U2 Parser | `actiontrack/parser.py` | `parse_note(path)` → `Note`; `MalformedNote`; strips code/comments/quotes; items from bullets, ACTION:, tables; owner/task split | `tests/test_parser.py` |
| U3 People | `actiontrack/people.py` | `resolve_owner(raw, attendees, known)` | `tests/test_people.py` |
| U4 Store | `actiontrack/store.py` | schema (items, sources, people), upsert with fuzzy dedup, recompute from sources, queries, `mark_done` | `tests/test_store.py` |
| U4b Store tests | | | `tests/test_store.py` (dedup pairs, edits, pruning, stickiness) |
| U5 Follow-up | `actiontrack/followup.py` | email building, `.eml` writer, Gmail draft via `claude -p` | `tests/test_followup.py` |
| U6 CLI | `actiontrack/cli.py`, `__main__.py` | argparse, ingest orchestration + report, list/done/followup | `tests/test_cli.py` (end-to-end on `notes/`), `tests/test_regressions.py` (code-review findings) |
| U7 Docs/data | `README.md`, `CLAUDE.md`, `people.json`, `notes/` | | |

Order: U1 → U2 → U3 → U4 → U6 (ingest/list/done) → U5 → followup → docs.

Design choices
- Item state is *derived* from its `sources` rows (recompute after every change). This makes ingest
  idempotent and order-independent, and lets `manual_done` override.
- Source identity = (file, owner + normalised task); changing `[ ]`→`[x]` or the due date updates that source row, and sources whose line vanished are pruned per file.
- Gmail: a standalone process can't call an MCP connector directly, so it shells out to
  `claude -p` with `--tools ""`, `--permission-mode dontAsk`, `--allowedTools` limited to the create-draft tool, and an empty temp cwd. Unit tests mock the subprocess.

Risks: Gmail tool name differs per connector (override with `ACTIONTRACK_GMAIL_TOOL`);
fuzzy matching is deliberately strict (75% token overlap + equal numbers) because a false merge silently
loses a task; verified on the sample notes (23 merges) and by `tests/test_store.py`.
