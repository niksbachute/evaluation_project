"""Parse one meeting-note markdown file into a Note with raw action items."""
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .dates import find_due, parse_meeting_date


class MalformedNote(Exception):
    """Raised when a note can't be used; message is the reason shown to the user."""


@dataclass
class RawItem:
    key: str                      # identity within the file: owner + normalised task
    done: bool
    owner_raw: str | None         # None = no owner written
    group: bool                   # owner was Everyone/Team/TBD...
    task: str
    due: date | None


@dataclass
class Note:
    path: Path
    date: date
    attendees: list
    items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


GROUP_WORDS = {"everyone", "everybody", "all", "team", "someone", "anyone", "tbd", "nobody", "we", "us"}
_STOP = {"the", "a", "an", "to", "for", "of", "on", "with", "and", "by", "in", "their", "all"}
_CHECK = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+?)\s*$")
_ACTION = re.compile(r"^\s*ACTION:\s*(.+?)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OWNER_TO = re.compile(r"^(?P<o>[^:|]{1,40}?)\s+to\s+(?P<t>.+)$", re.IGNORECASE)
_AT_OWNER = re.compile(r"^@(?P<o>[\w.-]+)\s*[:,-]?\s+(?P<t>.+)$")
_NAME_TOKEN = re.compile(r"^[A-Z][\w'-]*\.?$")
_DANGLING = {"by", "before", "due", "until", "from", "on", "for", "results"}
_PUNCT = " ,;:—–-"


def normalise(task):
    """Lower-case content words, used for duplicate detection."""
    words = re.findall(r"[a-z0-9]+", task.lower())
    return " ".join(w for w in words if w not in _STOP)


def _clean_lines(text):
    """Drop fenced code, HTML comments and blockquotes."""
    out, in_fence = [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    text = _COMMENT.sub("", "\n".join(out))
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]


def _meta(lines, raw_text):
    """Return (date_text, attendees_text) from front matter or header lines."""
    date_text = att_text = None
    if raw_text.startswith("---"):
        end = raw_text.find("\n---", 3)
        if end != -1:
            for ln in raw_text[3:end].splitlines():
                k, _, v = ln.partition(":")
                if k.strip().lower() == "date":
                    date_text = v.strip()
                elif k.strip().lower() == "attendees":
                    att_text = v.strip().strip("[]")
    for ln in lines:
        s = ln.strip()
        if date_text is None and s.lower().startswith("date:"):
            date_text = s[5:].strip()
        elif att_text is None and s.lower().startswith("attendees:"):
            att_text = s[10:].strip()
    return date_text, att_text


def _split_owners(owner_part):
    owner_part = re.sub(r"\(.*?\)", "", owner_part).strip().lstrip("@").rstrip(":")
    return [p.strip() for p in re.split(r"\s*(?:&|,|\band\b)\s*", owner_part) if p.strip()]


def _looks_like_owner(o):
    """A name (1-3 capitalised words) or a group word; rejects 'Review the plan'."""
    tokens = o.split()
    if o.lower() in GROUP_WORDS:
        return True
    return 1 <= len(tokens) <= 3 and all(_NAME_TOKEN.match(t) for t in tokens)


def _split_task(text):
    """'Priya to send X by Friday' -> (['Priya'], 'send X by Friday'); no owner -> ([], text)."""
    m = _AT_OWNER.match(text)
    if m:
        task = re.sub(r"^to\s+", "", m.group("t"), flags=re.IGNORECASE)
        return _split_owners(m.group("o")), task
    m = _OWNER_TO.match(text)
    if m and len(m.group("o").split()) <= 6:
        owners = _split_owners(m.group("o"))
        if owners and all(_looks_like_owner(o) for o in owners):
            return owners, m.group("t")
    return [], text


def _strip_dangling(s):
    """Remove trailing connector words ('by', 'due', ...) left behind after cutting out a date."""
    s = s.rstrip(_PUNCT)
    while s:
        head, _, last = s.rpartition(" ")
        if last.strip(_PUNCT).lower() not in _DANGLING:
            break
        s = head.rstrip(_PUNCT)
    return s


def _strip_due(task, ref):
    due, span = find_due(task, ref)
    if due is None:
        return task.strip(" .;,"), None
    task = (_strip_dangling(task[:span[0]]) + " " + task[span[1]:]).strip(" .;,—–-")
    return re.sub(r"\s+", " ", task), due


def _make_items(text, done, ref, owners=None, due_hint=None):
    if owners is None:
        owners, task = _split_task(text)
    else:
        task = text
    task, due = _strip_due(task, ref)
    due = due_hint or due
    if not task:
        return []
    norm = normalise(task)
    if not owners:
        return [RawItem(f"|{norm}", done, None, False, task, due)]
    return [RawItem(f"{o.lower()}|{norm}", done, o, o.lower() in GROUP_WORDS, task, due)
            for o in owners]


def _table_items(lines, ref):
    items, cols = [], None
    for ln in lines:
        s = ln.strip()
        if "|" not in s:
            cols = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        low = [c.lower() for c in cells]
        if "owner" in low and "action" in low:
            cols = {"owner": low.index("owner"), "action": low.index("action"),
                    "due": low.index("due") if "due" in low else None}
        elif cols and not set(s) <= set("|-: ") and max(cols["owner"], cols["action"]) < len(cells):
            owner, action = cells[cols["owner"]], cells[cols["action"]]
            due = None
            if cols["due"] is not None and cols["due"] < len(cells):
                due, _ = find_due(cells[cols["due"]], ref)
            owners = _split_owners(owner)
            if owners and action:
                items += _make_items(action, False, ref, owners=owners, due_hint=due)
    return items


def _collapse(items):
    """Merge repeated lines in one note: done only if every copy is done; keep the first due date."""
    merged = {}
    for it in items:
        first = merged.setdefault(it.key, it)
        if first is not it:
            first.done = first.done and it.done
            first.due = first.due or it.due
    return list(merged.values())


def parse_note(path):
    path = Path(path)
    data = path.read_bytes()
    if b"\x00" in data:
        raise MalformedNote("binary content, not a text note")
    try:
        raw_text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise MalformedNote("not valid UTF-8 text")
    lines = _clean_lines(raw_text)
    date_text, att_text = _meta(lines, raw_text)
    if not date_text:
        raise MalformedNote("missing Date")
    meeting_date = parse_meeting_date(date_text)
    if meeting_date is None:
        raise MalformedNote(f"invalid Date '{date_text}'")
    attendees = [a.strip() for a in (att_text or "").split(",") if a.strip()]
    note = Note(path, meeting_date, attendees)
    if not attendees:
        note.warnings.append("no attendees listed")
    items = []
    for ln in lines:
        m = _CHECK.match(ln)
        if m:
            items += _make_items(m.group(2), m.group(1) in "xX", meeting_date)
            continue
        m = _ACTION.match(ln)
        if m:
            items += _make_items(m.group(1), False, meeting_date)
    items += _table_items(lines, meeting_date)
    note.items = _collapse(items)
    return note
