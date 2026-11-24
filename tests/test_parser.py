from datetime import date

import pytest

from actiontrack.parser import MalformedNote, parse_note


def note(tmp_path, text, name="n.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return parse_note(p)


HEAD = "# Meeting: x\nDate: 2026-09-01\nAttendees: Priya Nair, Sam Okafor\n"


def test_basic_item(tmp_path):
    n = note(tmp_path, HEAD + "- [ ] Priya to send the revised quote by Friday\n- [x] Sam to ship it\n")
    assert n.date == date(2026, 9, 1) and n.attendees == ["Priya Nair", "Sam Okafor"]
    a, b = n.items
    assert (a.owner_raw, a.task, a.due, a.done) == ("Priya", "send the revised quote", date(2026, 9, 4), False)
    assert b.done and b.due is None


def test_bullets_checkbox_and_nesting(tmp_path):
    n = note(tmp_path, HEAD + "* [ ] A to a1\n+ [X] B to b1\n  - [ ] C to c1\n")
    assert [(i.owner_raw, i.done) for i in n.items] == [("A", False), ("B", True), ("C", False)]


def test_ignored_regions(tmp_path):
    n = note(tmp_path, HEAD + "> - [ ] Q to quoted\n```\n- [ ] F to fenced\n```\n"
             "<!-- - [ ] H to hidden -->\n<!--\n- [ ] M to multi\n-->\n- [ ] Real to keep\n")
    assert [i.owner_raw for i in n.items] == ["Real"]


def test_action_line_and_table(tmp_path):
    n = note(tmp_path, HEAD + "ACTION: Karan to circulate summary tomorrow\n\n"
             "| Owner | Action | Due |\n|---|---|---|\n| Anita | Refresh the brand kit | 2026-10-09 |\n")
    k, a = n.items
    assert (k.owner_raw, k.task, k.due) == ("Karan", "circulate summary", date(2026, 9, 2))
    assert (a.owner_raw, a.task, a.due) == ("Anita", "Refresh the brand kit", date(2026, 10, 9))


def test_owner_forms(tmp_path):
    n = note(tmp_path, HEAD + "- [ ] @anita: audit contrast by Mon\n- [ ] A & B to agree\n"
             "- [ ] Lena (with Priya) to collect\n- [ ] Everyone to review\n- [ ] Just a task\n")
    owners = [(i.owner_raw, i.group) for i in n.items]
    assert owners == [("anita", False), ("A", False), ("B", False), ("Lena", False),
                      ("Everyone", True), (None, False)]
    assert n.items[0].task == "audit contrast"


def test_dangling_words_removed(tmp_path):
    n = note(tmp_path, HEAD + "- [ ] Lena to run the survey, results due 15 October\n")
    assert n.items[0].task == "run the survey" and n.items[0].due == date(2026, 10, 15)


def test_front_matter(tmp_path):
    n = note(tmp_path, "---\ntitle: T\ndate: 2026-09-16\nattendees: [Anita Desai, Lena Fischer]\n---\n"
             "- [ ] Lena to draft by 2026-09-21\n")
    assert n.date == date(2026, 9, 16) and n.attendees == ["Anita Desai", "Lena Fischer"]
    assert n.items[0].due == date(2026, 9, 21)


def test_no_attendees_warns(tmp_path):
    n = note(tmp_path, "Date: 2026-09-23\n- [ ] Sam to x\n")
    assert n.attendees == [] and n.warnings


@pytest.mark.parametrize("text,reason", [
    ("# Meeting\n- [ ] A to b\n", "missing Date"),
    ("Date: sometime last week\n", "invalid Date"),
])
def test_malformed_text(tmp_path, text, reason):
    with pytest.raises(MalformedNote, match=reason):
        note(tmp_path, text)


def test_malformed_binary(tmp_path):
    p = tmp_path / "b.md"
    p.write_bytes(b"\xff\xfe\x00Date: \x00\x89PNG\x00")
    with pytest.raises(MalformedNote, match="binary"):
        parse_note(p)
