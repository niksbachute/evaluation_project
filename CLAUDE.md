# actiontrack

CLI that ingests meeting-note markdown, tracks action items in SQLite, drafts follow-up emails.

- Spec: `docs/SPEC.md` (source of truth). Plan: `docs/PLAN.md`. Change the spec first, then code.
- Run: `python -m actiontrack <ingest|list|done|followup> ...`  Tests: `python -m pytest -q`
- Python 3.10+, **stdlib only** at runtime. Keep it small; no extra layers or dependencies.
- Layout: `actiontrack/{dates,parser,people,store,followup,cli}.py`, tests in `tests/`, sample data in `notes/`.

Rules
- Never send email. Gmail path may only create drafts; the only tool allowed is the create-draft tool.
- Never guess an owner: ambiguous first names stay unresolved and are reported.
- Ingest must never crash on a bad file and must be idempotent; `done` is sticky.
- Item status/due are derived from `sources` rows (see `store.recompute`); don't write them elsewhere.
- Duplicate matching must stay strict (a false merge silently loses a task); add a case to `tests/test_store.py` when changing it.
- Every bug fix gets a regression test (see `tests/test_regressions.py`).
- Console output is forced to UTF-8 with replacement (`cli.main`), so Windows consoles never crash. "Today" always comes from `--today` / `ACTIONTRACK_TODAY` / system date, never hard-coded.
- Tests must use `--today`/temp DBs; never touch the real `actiontrack.db` or Gmail.
