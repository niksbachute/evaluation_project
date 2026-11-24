"""End-to-end tests on the sample notes/ folder (temp DB, fixed --today)."""
import re

import pytest

from actiontrack.cli import main
from conftest import NOTES

TODAY = ["--today", "2026-10-15"]


@pytest.fixture
def db(tmp_path):
    return ["--db", str(tmp_path / "t.db")]


def run(capsys, db, *args):
    code = main([*args, *db, *TODAY])
    out = capsys.readouterr()
    return code, out.out, out.err


def ingest(capsys, db):
    return run(capsys, db, "ingest", str(NOTES))


def test_ingest_reports_malformed_and_never_crashes(capsys, db):
    code, out, _ = ingest(capsys, db)
    assert code == 0
    assert "SKIPPED scratch.md" in out and "SKIPPED untitled.md" in out
    assert "SKIPPED 2026-10-03-sales-pipeline.md" in out
    assert "ignored 2026-09-19-offsite-draft.txt" in out
    assert "no attendees listed" in out


def test_missing_folder(capsys, db):
    code, _, err = run(capsys, db, "ingest", "no/such/folder")
    assert code == 2 and "not found" in err


def test_ingest_idempotent_and_done_sticky(capsys, db):
    ingest(capsys, db)
    _, before, _ = run(capsys, db, "list")
    run(capsys, db, "done", "6")
    code, out, _ = ingest(capsys, db)
    assert "0 added, 0 merged duplicates, 0 updated" in out
    _, after, _ = run(capsys, db, "list")
    assert after.count("\n") == before.count("\n")           # no duplicate rows
    _, done_list, _ = run(capsys, db, "list", "--status", "done")
    assert "share the VPN guide" in done_list


def test_duplicates_merged_latest_wins(capsys, db):
    ingest(capsys, db)
    _, out, _ = run(capsys, db, "list", "--owner", "Priya Nair")
    assert out.count("send the revised quote to Acme") == 1
    assert "done" in next(l for l in out.splitlines() if "revised quote" in l)
    _, out, _ = run(capsys, db, "list", "--owner", "Rahul Mehta")
    assert out.count("fix the pagination bug") == 1 and "2026-09-23" in out   # latest due (Wed 23 Sep)
    assert out.count("deploy the beta to staging") == 1


def test_same_first_name_never_conflated(capsys, db):
    ingest(capsys, db)
    _, out, _ = run(capsys, db, "list", "--owner", "Priya Shah")
    assert "triage the open bug list" in out and "renewal one-pager" not in out
    _, out, _ = run(capsys, db, "list", "--owner", "Priya Nair")
    assert "renewal one-pager" in out and "triage the open bug list" not in out
    _, out, _ = run(capsys, db, "list", "--owner", "Priya")          # first name: both + ambiguous
    assert "Priya?" in out and "Priya Shah" in out and "Priya Nair" in out


def test_non_items_not_ingested(capsys, db):
    ingest(capsys, db)
    _, out, _ = run(capsys, db, "list")
    for text in ("hardware tokens", "Owner to remediate", "Book the venue", "chase the vendor"):
        assert text not in out
    assert out.count("refund affected customers") == 1
    line = next(l for l in out.splitlines() if "refund affected" in l)
    assert " - " in line                                              # no due date from the quote


def test_unowned_and_undated(capsys, db):
    ingest(capsys, db)
    _, out, _ = run(capsys, db, "list")
    assert "(someone)" in out and "(everyone)" in out and "(tbd)" in out and "(team)" in out
    _, out, _ = run(capsys, db, "list", "--status", "overdue")
    assert "share the VPN guide" not in out                           # no due date -> never overdue


def test_list_filters(capsys, db):
    ingest(capsys, db)
    _, out, _ = run(capsys, db, "list", "--status", "overdue")
    rows = out.splitlines()[1:-2]
    assert rows and all(l.split()[1] == "overdue" for l in rows)
    _, out, _ = run(capsys, db, "list", "--due-before", "2026-09-05")
    rows = out.splitlines()[1:-2]
    due = [re.search(r"\d{4}-\d{2}-\d{2}", l).group() for l in rows]   # first date in a row = DUE column
    assert due and all(d < "2026-09-05" for d in due)
    code, out, _ = run(capsys, db, "list", "--owner", "Nobody Here")
    assert code == 0 and "No items match" in out


def test_done_command(capsys, db):
    ingest(capsys, db)
    assert run(capsys, db, "done", "3")[0] == 0
    assert "already done" in run(capsys, db, "done", "3")[1]
    code, _, err = run(capsys, db, "done", "9999")
    assert code == 1 and "no item" in err


def test_followup_dry_run(capsys, db):
    ingest(capsys, db)
    code, out, _ = run(capsys, db, "followup", "Priya Nair", "--dry-run", "--people", "people.json")
    assert code == 0 and "priya.nair@example.com" in out
    assert out.index("Overdue:") < out.index("Open:")
    assert "renewal one-pager" in out and "triage the open bug list" not in out
    assert "ambiguous 'Priya'" in out


def test_followup_ambiguous_first_name(capsys, db):
    ingest(capsys, db)
    code, _, err = run(capsys, db, "followup", "Rahul", "--dry-run")
    assert code == 2 and "Rahul Mehta" in err and "Rahul Verma" in err
    code, out, _ = run(capsys, db, "followup", "Sam", "--dry-run")
    assert code == 0 and "Sam Okafor" in out


def test_followup_eml_and_all(capsys, db, tmp_path):
    ingest(capsys, db)
    d = str(tmp_path / "drafts")
    code, out, _ = run(capsys, db, "followup", "--all", "--eml", "--drafts-dir", d,
                       "--people", "people.json")
    eml = tmp_path / "drafts" / "sam_okafor.eml"
    assert code == 0 and eml.exists() and "To: sam.okafor@example.com" in eml.read_text()
    assert run(capsys, db, "followup")[0] == 2                        # owner or --all required


def test_followup_gmail_unavailable_falls_back(capsys, db, tmp_path, monkeypatch):
    from actiontrack import followup as fu

    def boom(*a, **k):
        raise fu.GmailUnavailable("connector not authorised")
    monkeypatch.setattr(fu, "create_gmail_draft", boom)
    ingest(capsys, db)
    code, _, err = run(capsys, db, "followup", "Sam", "--drafts-dir", str(tmp_path / "d"))
    assert code == 3 and "Gmail draft NOT created" in err and "nothing was sent" in err
    assert (tmp_path / "d" / "sam_okafor.eml").exists()


def test_followup_gmail_success(capsys, db, monkeypatch):
    from actiontrack import followup as fu
    calls = []
    monkeypatch.setattr(fu, "create_gmail_draft", lambda to, s, b: calls.append(to))
    ingest(capsys, db)
    code, out, _ = run(capsys, db, "followup", "Sam", "--people", "people.json")
    assert code == 0 and calls == ["sam.okafor@example.com"] and "not sent" in out
