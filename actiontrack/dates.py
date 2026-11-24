"""Date parsing: meeting dates and due-date phrases resolved against a reference date."""
import calendar
import re
from datetime import date, timedelta

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thurs": 3, "thur": 3, "thu": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _alt(words):
    return "|".join(sorted(words, key=len, reverse=True))


_WD = _alt(WEEKDAYS)
_MON = _alt(MONTHS)
F = re.IGNORECASE

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(
    rf"(?:\b(?:{_WD})\.?,?\s+)?\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\b(?:,?\s+(\d{{4}}))?", F)
_MONTH_DAY = re.compile(
    rf"(?:\b(?:{_WD})\.?,?\s+)?\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", F)
_MID = re.compile(rf"\bmid[- ]?({_MON})\b", F)
_END_OF = re.compile(r"\b(?:end of(?: the)?\s+(next )?(week|month)|(eow))\b", F)
_TOMORROW = re.compile(r"\b(?:(?:eod|end of day|cob)\s+)?tomorrow\b", F)
_EOD = re.compile(r"\b(?:eod|end of day|cob)\b", F)
_TODAY = re.compile(r"\b(?:today|tonight)\b", F)
_WD_NEXT_WEEK = re.compile(rf"\b({_WD})\s+next\s+week\b", F)
_WEEKDAY = re.compile(rf"\b(next\s+)?({_WD})\b", F)
_IN_N = re.compile(r"\bin\s+(\d{1,2})\s+(day|week)s?\b", F)
_THE_NTH = re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", F)
# A bare weekday / today / tomorrow only counts as a due date after a cue word or at the end of
# the text, and never when possessive ("Monday's PR"), so "review the Monday report" stays a task.
_CUE = re.compile(r"\b(?:by|before|on|until|till|due|for|this|from)\s*$", F)
_POSSESSIVE = re.compile(r"\s*['’]s\b")

_MEETING_FORMS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\.?,?\s+(\d{{4}})\b", F), "dmy"),
    (re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", F), "mdy"),
]


def _mk(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_meeting_date(text):
    """Parse a meeting header date; return a date or None."""
    for rx, kind in _MEETING_FORMS:
        m = rx.search(text or "")
        if not m:
            continue
        a, b, c = m.groups()
        if kind == "ymd":
            return _mk(a, b, c)
        if kind == "dmy":
            return _mk(c, MONTHS[b.lower()], a)
        return _mk(c, MONTHS[a.lower()], b)
    return None


def _with_year(month, day, year, ref):
    if year:
        return _mk(year, month, day)
    d = _mk(ref.year, month, day)
    if d and d < ref - timedelta(days=60):
        d = _mk(ref.year + 1, month, day)
    return d


def _week_monday(ref):
    return ref - timedelta(days=ref.weekday())


def _cued(rx, text):
    """First match of rx that is a plausible due phrase (see _CUE), else None."""
    for m in rx.finditer(text):
        if _POSSESSIVE.match(text[m.end():]):
            continue
        if _CUE.search(text[:m.start()]) or not text[m.end():].strip(" .,;:!)"):
            return m
    return None


def find_due(text, ref):
    """Find a due phrase in text. Returns (date, (start, end)) or (None, None)."""
    m = _ISO.search(text)
    if m:
        d = _mk(*m.groups())
        if d:
            return d, m.span()
    m = _DAY_MONTH.search(text)
    if m:
        d = _with_year(MONTHS[m.group(2).lower()], m.group(1), m.group(3), ref)
        if d:
            return d, m.span()
    m = _MONTH_DAY.search(text)
    if m:
        d = _with_year(MONTHS[m.group(1).lower()], m.group(2), m.group(3), ref)
        if d:
            return d, m.span()
    m = _MID.search(text)
    if m:
        d = _with_year(MONTHS[m.group(1).lower()], 15, None, ref)
        if d:
            return d, m.span()
    m = _END_OF.search(text)
    if m:
        nxt, unit = bool(m.group(1)), (m.group(2) or "week").lower()
        if unit == "week":
            d = _week_monday(ref) + timedelta(days=4 + (7 if nxt else 0))
            if d < ref:  # weekend meeting: the coming Friday
                d += timedelta(days=7)
        else:
            y, mo = (ref.year + (ref.month == 12), ref.month % 12 + 1) if nxt else (ref.year, ref.month)
            d = date(y, mo, calendar.monthrange(y, mo)[1])
        return d, m.span()
    m = _WD_NEXT_WEEK.search(text)               # "Friday next week"
    if m:
        return _week_monday(ref) + timedelta(days=7 + WEEKDAYS[m.group(1).lower()]), m.span()
    m = _IN_N.search(text)
    if m:
        return ref + timedelta(days=int(m.group(1)) * (7 if m.group(2).lower() == "week" else 1)), m.span()
    m = _THE_NTH.search(text)                    # "by the 15th": next occurrence on/after the meeting
    if m:
        day = int(m.group(1))
        d = _mk(ref.year, ref.month, day)
        if d and d < ref:
            d = _mk(ref.year + (ref.month == 12), ref.month % 12 + 1, day)
        if d:
            return d, m.span()
    m = _cued(_TOMORROW, text)
    if m:
        return ref + timedelta(days=1), m.span()
    m = _EOD.search(text)
    if m:
        return ref, m.span()
    m = _cued(_TODAY, text)
    if m:
        return ref, m.span()
    m = _cued(_WEEKDAY, text)
    if m:
        wd = WEEKDAYS[m.group(2).lower()]
        if m.group(1):
            d = _week_monday(ref) + timedelta(days=7 + wd)
        else:
            d = ref + timedelta(days=(wd - ref.weekday()) % 7)
        return d, m.span()
    return None, None
