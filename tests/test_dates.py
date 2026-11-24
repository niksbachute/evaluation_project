from datetime import date

import pytest

from actiontrack.dates import find_due, parse_meeting_date

D = date


@pytest.mark.parametrize("text,ref,want", [
    ("send by Friday", D(2026, 9, 1), D(2026, 9, 4)),
    ("by Friday", D(2026, 9, 4), D(2026, 9, 4)),                 # same day counts
    ("by Wed", D(2026, 9, 8), D(2026, 9, 9)),
    ("by next Tuesday", D(2026, 10, 5), D(2026, 10, 13)),
    ("by tomorrow", D(2026, 9, 2), D(2026, 9, 3)),
    ("by EOD tomorrow", D(2026, 9, 21), D(2026, 9, 22)),
    ("by EOD", D(2026, 10, 8), D(2026, 10, 8)),
    ("by end of next week", D(2026, 9, 3), D(2026, 9, 11)),
    ("by end of month", D(2026, 9, 14), D(2026, 9, 30)),
    ("by mid-October", D(2026, 9, 30), D(2026, 10, 15)),
    ("by Oct 3rd", D(2026, 9, 30), D(2026, 10, 3)),
    ("by Wed 16 Sep", D(2026, 9, 14), D(2026, 9, 16)),
    ("on Saturday 10 Oct", D(2026, 9, 29), D(2026, 10, 10)),
    ("due 15 October", D(2026, 9, 30), D(2026, 10, 15)),
    ("by 2026-09-08", D(2026, 9, 1), D(2026, 9, 8)),
    ("by 5 Jan", D(2026, 12, 20), D(2027, 1, 5)),                # year rollover
])
def test_find_due(text, ref, want):
    assert find_due(text, ref)[0] == want


@pytest.mark.parametrize("text", ["cut costs by 10%", "next quarter maybe", "review the monthly report", ""])
def test_no_due(text):
    assert find_due(text, D(2026, 9, 1))[0] is None


def test_meeting_dates():
    assert parse_meeting_date("2026-09-01") == D(2026, 9, 1)
    assert parse_meeting_date("9 September 2026") == D(2026, 9, 9)
    assert parse_meeting_date("Monday, 14 September 2026") == D(2026, 9, 14)
    assert parse_meeting_date("September 9, 2026") == D(2026, 9, 9)
    assert parse_meeting_date("sometime last week") is None
    assert parse_meeting_date("2026-13-45") is None
