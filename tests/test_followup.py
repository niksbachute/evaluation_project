import subprocess
from datetime import date

import pytest

from actiontrack import followup as fu


def test_gmail_tool_is_create_only():
    assert "send" not in fu.GMAIL_TOOL.lower() and "create" in fu.GMAIL_TOOL


def test_no_claude_cli(monkeypatch):
    monkeypatch.setattr(fu.shutil, "which", lambda n: None)
    with pytest.raises(fu.GmailUnavailable, match="not on PATH"):
        fu.create_gmail_draft("a@b.c", "s", "b")


def _fake_run(stdout, code=0):
    return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, "")


def test_gmail_success_and_failure(monkeypatch):
    monkeypatch.setattr(fu.shutil, "which", lambda n: "claude")
    monkeypatch.setattr(fu.subprocess, "run", _fake_run("DRAFT_CREATED"))
    fu.create_gmail_draft("a@b.c", "s", "b")
    monkeypatch.setattr(fu.subprocess, "run", _fake_run("FAILED: not authenticated"))
    with pytest.raises(fu.GmailUnavailable, match="not authenticated"):
        fu.create_gmail_draft("a@b.c", "s", "b")


def test_prompt_forbids_sending_and_limits_tools(monkeypatch):
    seen = {}

    def run(cmd, **k):
        seen.update(cmd=cmd, prompt=k["input"])
        return subprocess.CompletedProcess(cmd, 0, "DRAFT_CREATED", "")
    monkeypatch.setattr(fu.shutil, "which", lambda n: "claude")
    monkeypatch.setattr(fu.subprocess, "run", run)
    fu.create_gmail_draft("a@b.c", "subj", "body")
    assert seen["cmd"][-1] == fu.GMAIL_TOOL and "Do NOT send" in seen["prompt"]


def test_build_email_orders_overdue_first():
    rows = [
        {"id": 2, "state": "open", "due_date": "2026-10-20", "task": "b", "source_file": "f2.md"},
        {"id": 1, "state": "overdue", "due_date": "2026-10-01", "task": "a", "source_file": "f1.md"},
    ]
    subject, body = fu.build_email("Sam Okafor", rows, date(2026, 10, 15), {1: "2026-09-01", 2: "2026-09-02"})
    assert "2 open" in subject and "1 overdue" in subject and body.startswith("Hi Sam,")
    assert body.index("[#1]") < body.index("[#2]") and "f1.md" in body and "2026-10-01" in body
