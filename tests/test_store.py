"""Store-level tests: duplicate detection, derived state, edits between ingests, stickiness."""
import time
from datetime import date

import pytest

from actiontrack.parser import normalise, parse_note
from actiontrack.store import Store, similar


def n(text):
    return normalise(text)


@pytest.mark.parametrize("a,b", [
    ("review PR 12", "review PR 13"),
    ("draft Q3 report", "draft Q4 report"),
    ("fix login bug", "fix logout bug"),
    ("book room for Monday demo", "book room for Tuesday demo"),
])
def test_distinct_short_tasks_not_merged(a, b):
    assert not similar(n(a), n(b))


@pytest.mark.parametrize("a,b", [
    ("send the revised quote to Acme", "send revised quote to Acme"),
    ("finalise the welcome-email copy", "Finalise welcome email copy"),
])
def test_same_task_merged(a, b):
    assert similar(n(a), n(b))


HEAD = "# Meeting\nDate: {d}\nAttendees: Sam Okafor, Priya Nair\n"


def ingest(store, tmp_path, name, d, body):
    p = tmp_path / name
    p.write_text(HEAD.format(d=d) + body, encoding="utf-8")
    note = parse_note(p)
    for it in note.items:
        owner = {"Sam": "Sam Okafor", "Priya": "Priya Nair"}.get(it.owner_raw)
        store.upsert(note, it, owner, False)
    store.prune(name, {it.key for it in note.items})
    store.db.commit()
    return store.items(date(2026, 10, 15))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_false_merges_do_not_happen(store, tmp_path):
    items = ingest(store, tmp_path, "a.md", "2026-09-01",
                   "- [ ] Sam to review PR 12\n- [ ] Sam to review PR 13\n"
                   "- [ ] Sam to draft Q3 report\n- [ ] Sam to draft Q4 report\n")
    assert len(items) == 4


def test_ownerless_items_only_merge_when_identical(store, tmp_path):
    items = ingest(store, tmp_path, "a.md", "2026-09-01", "- [ ] chase the vendor today\n- [ ] chase vendors\n")
    assert len(items) == 2


def test_latest_meeting_wins_and_keeps_earlier_due(store, tmp_path):
    ingest(store, tmp_path, "a.md", "2026-09-01", "- [ ] Sam to send the report by 2026-09-04\n")
    items = ingest(store, tmp_path, "b.md", "2026-09-08", "- [x] Sam to send the report\n")
    assert len(items) == 1 and items[0]["status"] == "done" and items[0]["due_date"] == "2026-09-04"


def test_edit_due_and_flip_back_stays_consistent(store, tmp_path):
    line = "- [ ] Sam to send the report by {}\n"
    ingest(store, tmp_path, "a.md", "2026-10-01", line.format("2026-10-02"))
    ingest(store, tmp_path, "a.md", "2026-10-01", "- [x] Sam to send the report by 2026-10-09\n")
    items = ingest(store, tmp_path, "a.md", "2026-10-01", "- [x] Sam to send the report by 2026-10-02\n")
    assert len(items) == 1 and items[0]["status"] == "done" and items[0]["due_date"] == "2026-10-02"


def test_removed_line_pruned_unless_done_by_hand(store, tmp_path):
    ingest(store, tmp_path, "a.md", "2026-10-01", "- [ ] Sam to keep this\n- [ ] Sam to drop this\n- [ ] Sam to hand-close\n")
    store.mark_done(3)
    items = ingest(store, tmp_path, "a.md", "2026-10-01", "- [ ] Sam to keep this\n")
    assert {i["task"] for i in items} == {"keep this", "hand-close"}


def test_in_file_duplicate_lines_are_idempotent(store, tmp_path):
    body = "- [x] Sam to dup line\n- [ ] Sam to dup line\n"
    ingest(store, tmp_path, "a.md", "2026-10-01", body)
    p = tmp_path / "a.md"
    note = parse_note(p)
    assert len(note.items) == 1 and not note.items[0].done          # done only if every copy is done
    assert [store.upsert(note, it, "Sam Okafor", False) for it in note.items] == ["unchanged"]


def test_done_is_sticky_and_reported(store, tmp_path):
    ingest(store, tmp_path, "a.md", "2026-10-01", "- [ ] Sam to ship it\n")
    assert store.mark_done(1) == "done" and store.mark_done(1) == "already" and store.mark_done(9) == "missing"
    items = ingest(store, tmp_path, "b.md", "2026-10-08", "- [ ] Sam to ship it\n")
    assert items[0]["status"] == "done"


def test_status_derivation(store, tmp_path):
    ingest(store, tmp_path, "a.md", "2026-10-01",
           "- [ ] Sam to a by 2026-10-02\n- [ ] Sam to b by 2026-10-20\n- [ ] Sam to c\n- [x] Sam to d by 2026-10-02\n")
    assert [i["state"] for i in store.items(date(2026, 10, 15))] == ["overdue", "open", "open", "done"]


def test_ids_stable(store, tmp_path):
    ingest(store, tmp_path, "a.md", "2026-10-01", "- [ ] Sam to a\n- [ ] Priya to b\n")
    before = [(i["id"], i["task"]) for i in store.items(date(2026, 10, 15))]
    ingest(store, tmp_path, "a.md", "2026-10-01", "- [ ] Sam to a\n- [ ] Priya to b\n")
    assert [(i["id"], i["task"]) for i in store.items(date(2026, 10, 15))] == before


def test_pathological_note_does_not_hang(tmp_path):
    p = tmp_path / "evil.md"
    p.write_text(HEAD.format(d="2026-10-01") + "- [ ] Sam to send it " + "by " * 3000 + "x 5 Oct\n", encoding="utf-8")
    t = time.time()
    parse_note(p)
    assert time.time() - t < 2
