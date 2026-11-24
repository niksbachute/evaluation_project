"""actiontrack command line: ingest | list | done | followup."""
import argparse
import os
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from . import followup as fu
from .parser import MalformedNote, parse_note
from .people import resolve_owner
from .store import Store


def _date_arg(s):
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date '{s}' (use YYYY-MM-DD)")


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS, help="SQLite file (default actiontrack.db)")
    common.add_argument("--today", type=_date_arg, default=argparse.SUPPRESS,
                        help="reference date YYYY-MM-DD (default: system date)")
    p = argparse.ArgumentParser(prog="actiontrack", parents=[common],
                                description="Track action items from meeting notes.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", parents=[common], help="parse a folder of .md meeting notes")
    s.add_argument("folder")

    s = sub.add_parser("list", parents=[common], help="show action items")
    s.add_argument("--owner")
    s.add_argument("--status", choices=["open", "done", "overdue"])
    s.add_argument("--due-before", type=_date_arg, metavar="DATE")

    s = sub.add_parser("done", parents=[common], help="mark an item done")
    s.add_argument("id", type=int)

    s = sub.add_parser("followup", parents=[common], help="draft follow-up email(s); never sends")
    s.add_argument("owner", nargs="?")
    s.add_argument("--all", action="store_true", help="one draft per owner with open items")
    s.add_argument("--dry-run", action="store_true", help="print the email, create nothing")
    s.add_argument("--eml", action="store_true", help="write a .eml file instead of a Gmail draft")
    s.add_argument("--people", default="people.json", help="JSON map of full name -> email")
    s.add_argument("--drafts-dir", default="drafts")
    return p


def _ctx(args):
    db = getattr(args, "db", None) or os.environ.get("ACTIONTRACK_DB", "actiontrack.db")
    today = getattr(args, "today", None)
    if today is None:
        env = os.environ.get("ACTIONTRACK_TODAY")
        try:
            today = date.fromisoformat(env) if env else date.today()
        except ValueError:
            raise ValueError(f"invalid ACTIONTRACK_TODAY '{env}' (use YYYY-MM-DD)")
    try:
        return Store(db), today
    except sqlite3.Error as e:
        raise sqlite3.Error(f"cannot open database '{db}': {e}")


# --- ingest -------------------------------------------------------------------
def cmd_ingest(args, store, today):
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"error: folder not found: {folder}", file=sys.stderr)
        return 2
    subdirs = sorted(p.name for p in folder.iterdir() if p.is_dir())
    all_files = sorted(p for p in folder.iterdir() if p.is_file())
    md = [p for p in all_files if p.suffix.lower() == ".md"]
    ignored = [p.name for p in all_files if p.suffix.lower() != ".md"]
    notes, skipped = [], []
    for p in md:
        try:
            notes.append(parse_note(p))
        except MalformedNote as e:
            skipped.append((p.name, str(e)))
        except Exception as e:  # a bad file must never abort the whole ingest
            skipped.append((p.name, f"could not be parsed ({type(e).__name__}: {e})"))

    known = set(store.people())
    for n in notes:
        known.update(n.attendees)
    store.add_people(known)

    counts, warnings, removed = Counter(), [], 0
    for n in sorted(notes, key=lambda n: (n.date, n.path.name)):
        name = n.path.name
        for w in n.warnings:
            warnings.append(f"{name}: {w}")
        for it in n.items:
            owner, amb = None, False
            if it.owner_raw and not it.group:
                r = resolve_owner(it.owner_raw, n.attendees, known)
                owner, amb = r.owner, r.ambiguous
                if amb:
                    warnings.append(f"{name}: ambiguous owner '{it.owner_raw}' "
                                    f"({' / '.join(r.candidates)}) for: {it.task}")
                elif owner not in known:
                    warnings.append(f"{name}: unknown owner '{owner}' (not an attendee anywhere) "
                                    f"for: {it.task}")
            elif it.group:
                warnings.append(f"{name}: unassigned (owner '{it.owner_raw}') for: {it.task}")
            else:
                warnings.append(f"{name}: no owner for: {it.task}")
            if it.due is None and not it.done:
                warnings.append(f"{name}: no due date for: {it.task}")
            counts[store.upsert(n, it, owner, amb)] += 1
        removed += store.prune(name, {it.key for it in n.items})
    store.db.commit()

    print(f"Files: {len(notes)} parsed, {len(skipped)} skipped, {len(ignored)} ignored (not .md)")
    for name, why in skipped:
        print(f"  SKIPPED {name}: {why}")
    for name in ignored:
        print(f"  ignored {name}")
    if subdirs:
        print(f"  note: {len(subdirs)} subfolder(s) not scanned: {', '.join(subdirs)}")
    print(f"Items: {counts['added']} added, {counts['merged']} merged duplicates, "
          f"{counts['updated']} updated, {counts['unchanged']} unchanged, {removed} removed "
          "(no longer in their note)")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")
    return 0


# --- list ---------------------------------------------------------------------
def _owner_label(r):
    if r["owner"]:
        return r["owner"]
    if r["ambiguous"]:
        return f"{r['owner_raw']}?"
    return r["owner_raw"] and f"({r['owner_raw'].lower()})" or "-"


def _cut(s, n):
    return s if len(s) <= n else s[: n - 3] + "..."


def cmd_list(args, store, today):
    rows = store.items(today, args.owner, args.status, args.due_before)
    if not rows:
        print("No items match.")
        return 0
    print(f"{'ID':>3}  {'STATUS':<7} {'OWNER':<14} {'DUE':<10}  {'TASK':<58} SOURCE")
    for r in rows:
        print(f"{r['id']:>3}  {r['state']:<7} {_cut(_owner_label(r), 14):<14} "
              f"{r['due_date'] or '-':<10}  {_cut(r['task'], 58):<58} {r['source_file']}")
    print(f"\n{len(rows)} item(s); reference date {today.isoformat()}")
    return 0


# --- done ---------------------------------------------------------------------
def cmd_done(args, store, today):
    res = store.mark_done(args.id)
    if res == "missing":
        print(f"error: no item with id {args.id}", file=sys.stderr)
        return 1
    print(f"Item {args.id} marked done." if res == "done" else f"Item {args.id} was already done.")
    return 0


# --- followup -----------------------------------------------------------------
def _resolve_followup_owner(store, query):
    """Returns (owner, None) or (None, error message)."""
    owners = store.owners()
    q = query.strip().lower()
    exact = [o for o in owners if o.lower() == q]
    if exact:
        return exact[0], None
    first = [o for o in owners if o.split()[0].lower() == q]
    if len(first) == 1:
        return first[0], None
    if len(first) > 1:
        return None, f"'{query}' is ambiguous; use a full name: " + ", ".join(first)
    return None, f"no owner matching '{query}'. Known owners: " + ", ".join(owners)


def _followup_one(args, store, today, owner, people):
    rows = [r for r in store.items(today, owner=owner) if r["owner"] == owner and r["state"] != "done"]
    if not rows:
        print(f"{owner}: no open or overdue items, nothing to draft.")
        return 0
    latest = {r["id"]: store.sources(r["id"])[-1]["meeting_date"] for r in rows}
    subject, body = fu.build_email(owner, rows, today, latest)
    to = people.get(owner)
    first = owner.split()[0].lower()
    unsure = [r for r in store.items(today) if r["ambiguous"] and (r["owner_raw"] or "").lower() == first
              and r["state"] != "done"]
    print(f"=== {owner} <{to or 'no email in people.json'}> ===")
    if not to:
        print(f"warning: no email for {owner} in {args.people}; draft will have no recipient")
    if unsure:
        print(f"note: {len(unsure)} open item(s) assigned to ambiguous '{owner.split()[0]}' were NOT included:")
        for r in unsure:
            print(f"  #{r['id']} {r['task']}")
    if args.dry_run:
        print(f"Subject: {subject}\n\n{body}\n")
        return 0
    eml = Path(args.drafts_dir) / f"{fu.safe_name(owner)}.eml"
    if args.eml:
        print(f"Wrote {fu.write_eml(eml, to, subject, body)}")
        return 0
    try:
        fu.create_gmail_draft(to, subject, body)
    except fu.GmailUnavailable as e:
        path = fu.write_eml(eml, to, subject, body)
        print(f"ERROR: Gmail draft NOT created: {e}", file=sys.stderr)
        print(f"Fallback: saved {path} instead (nothing was sent).", file=sys.stderr)
        return 3
    print(f"Gmail draft created for {owner} (not sent).")
    return 0


def cmd_followup(args, store, today):
    if bool(args.owner) == bool(args.all):
        print("error: give an owner or --all (not both)", file=sys.stderr)
        return 2
    people = fu.load_people(args.people)
    if args.all:
        # only real people (attendees somewhere); a mis-parsed "owner" must never get an email
        real = set(store.people())
        with_items = {r["owner"] for r in store.items(today) if r["owner"] and r["state"] != "done"}
        owners = sorted(with_items & real)
        for o in sorted(with_items - real):
            print(f"skipped '{o}': not a known attendee (check the notes)")
    else:
        owner, err = _resolve_followup_owner(store, args.owner)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        owners = [owner]
    code = 0
    for o in owners:
        code = max(code, _followup_one(args, store, today, o, people))
    return code


COMMANDS = {"ingest": cmd_ingest, "list": cmd_list, "done": cmd_done, "followup": cmd_followup}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        store, today = _ctx(args)
    except (ValueError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        code = COMMANDS[args.cmd](args, store, today)
        store.db.commit()
        return code
    except BaseException:
        store.db.rollback()  # no half-committed ingest
        raise
    finally:
        store.close()
