"""SQLite store. Item status/due are derived from `sources` rows (see recompute)."""
import sqlite3

from .parser import normalise

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner TEXT,              -- resolved full name, or NULL
  owner_raw TEXT,          -- as written in the note
  owner_key TEXT NOT NULL, -- dedup key
  ambiguous INTEGER NOT NULL DEFAULT 0,
  task TEXT NOT NULL,
  task_norm TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',   -- open | done  (overdue is derived)
  manual_done INTEGER NOT NULL DEFAULT 0,
  due_date TEXT,
  source_file TEXT
);
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES items(id),
  file TEXT NOT NULL,
  meeting_date TEXT NOT NULL,
  line_key TEXT NOT NULL,
  done INTEGER NOT NULL,
  due_date TEXT,
  UNIQUE (file, line_key)
);
"""

def similar(a, b):
    """Same task? Numbers must match exactly and at least 75% of the content words must be shared."""
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    if {w for w in ta if any(c.isdigit() for c in w)} != {w for w in tb if any(c.isdigit() for c in w)}:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.75


def owner_key(owner, owner_raw):
    if owner:
        return owner
    return "?" + owner_raw.lower() if owner_raw else ""


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # --- people -----------------------------------------------------------
    def people(self):
        return [r["name"] for r in self.db.execute("SELECT name FROM people")]

    def add_people(self, names):
        self.db.executemany("INSERT OR IGNORE INTO people VALUES (?)", [(n,) for n in names])

    # --- ingest -----------------------------------------------------------
    def upsert(self, note, item, owner, ambiguous):
        """Record one raw item from a note. Returns 'added', 'merged', 'updated' or 'unchanged'."""
        file = note.path.name
        mdate = note.date.isoformat()
        due = item.due.isoformat() if item.due else None
        src = self.db.execute("SELECT * FROM sources WHERE file=? AND line_key=?",
                              (file, item.key)).fetchone()
        if src:
            if (src["done"], src["due_date"], src["meeting_date"]) == (int(item.done), due, mdate):
                return "unchanged"
            self.db.execute("UPDATE sources SET done=?, due_date=?, meeting_date=? WHERE id=?",
                            (int(item.done), due, mdate, src["id"]))
            before = self._state(src["item_id"])
            self.recompute(src["item_id"])
            return "updated" if self._state(src["item_id"]) != before else "unchanged"

        key = owner_key(owner, item.owner_raw)
        norm = normalise(item.task)
        item_id, outcome = None, "merged"
        for row in self.db.execute("SELECT id, task_norm FROM items WHERE owner_key=?", (key,)):
            # ownerless items are only merged when identical: nothing else ties them together
            if (norm == row["task_norm"]) if key == "" else similar(norm, row["task_norm"]):
                item_id = row["id"]
                break
        if item_id is None:
            cur = self.db.execute(
                "INSERT INTO items (owner, owner_raw, owner_key, ambiguous, task, task_norm)"
                " VALUES (?,?,?,?,?,?)",
                (owner, item.owner_raw, key, int(ambiguous), item.task, norm))
            item_id, outcome = cur.lastrowid, "added"
        self.db.execute(
            "INSERT INTO sources (item_id, file, meeting_date, line_key, done, due_date)"
            " VALUES (?,?,?,?,?,?)", (item_id, file, mdate, item.key, int(item.done), due))
        self.recompute(item_id)
        return outcome

    def prune(self, file, keep_keys):
        """Drop sources of `file` whose line is no longer in it; remove items left with no source
        (unless marked done by hand). Call after upserting everything from the file."""
        stale = [r for r in self.db.execute("SELECT id, item_id, line_key FROM sources WHERE file=?", (file,))
                 if r["line_key"] not in keep_keys]
        removed = 0
        for r in stale:
            self.db.execute("DELETE FROM sources WHERE id=?", (r["id"],))
            if self.db.execute("SELECT 1 FROM sources WHERE item_id=?", (r["item_id"],)).fetchone():
                self.recompute(r["item_id"])
            elif not self.db.execute("SELECT manual_done FROM items WHERE id=?", (r["item_id"],)).fetchone()[0]:
                self.db.execute("DELETE FROM items WHERE id=?", (r["item_id"],))
                removed += 1
        return removed

    def _state(self, item_id):
        r = self.db.execute("SELECT status, due_date FROM items WHERE id=?", (item_id,)).fetchone()
        return (r["status"], r["due_date"])

    def recompute(self, item_id):
        """Status and due come from the latest meeting; manual 'done' always wins."""
        srcs = self.db.execute(
            "SELECT * FROM sources WHERE item_id=? ORDER BY meeting_date, file, id", (item_id,)).fetchall()
        latest = srcs[-1]
        due = next((s["due_date"] for s in reversed(srcs) if s["due_date"]), None)
        manual = self.db.execute("SELECT manual_done FROM items WHERE id=?", (item_id,)).fetchone()[0]
        status = "done" if manual or latest["done"] else "open"
        self.db.execute("UPDATE items SET status=?, due_date=?, source_file=? WHERE id=?",
                        (status, due, latest["file"], item_id))

    def mark_done(self, item_id):
        """Returns 'done', 'already' or 'missing'."""
        row = self.db.execute("SELECT status FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return "missing"
        if row["status"] == "done":
            self.db.execute("UPDATE items SET manual_done=1 WHERE id=?", (item_id,))
            return "already"
        self.db.execute("UPDATE items SET status='done', manual_done=1 WHERE id=?", (item_id,))
        return "done"

    # --- queries ----------------------------------------------------------
    def items(self, today, owner=None, status=None, due_before=None):
        rows = [dict(r) for r in self.db.execute("SELECT * FROM items ORDER BY id")]
        for r in rows:
            r["state"] = item_state(r, today)
        if status:
            rows = [r for r in rows if r["state"] == status]
        if due_before:
            rows = [r for r in rows if r["due_date"] and r["due_date"] < due_before.isoformat()]
        if owner:
            rows = [r for r in rows if owner_matches(r, owner)]
        return rows

    def owners(self):
        return sorted(r[0] for r in self.db.execute(
            "SELECT DISTINCT owner FROM items WHERE owner IS NOT NULL"))

    def sources(self, item_id):
        return self.db.execute(
            "SELECT file, meeting_date FROM sources WHERE item_id=? ORDER BY meeting_date, file",
            (item_id,)).fetchall()


def item_state(row, today):
    if row["status"] == "done":
        return "done"
    if row["due_date"] and row["due_date"] < today.isoformat():
        return "overdue"
    return "open"


def owner_matches(row, query):
    q = query.strip().lower()
    if row["owner"]:
        return q == row["owner"].lower() or q == row["owner"].split()[0].lower()
    return bool(row["owner_raw"]) and q == row["owner_raw"].split()[0].lower()
