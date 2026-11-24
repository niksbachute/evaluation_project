"""Owner resolution: map a name as written in a note to a known person, never guessing."""
from dataclasses import dataclass, field


@dataclass
class Resolution:
    owner: str | None            # resolved full name, or None
    ambiguous: bool = False
    candidates: list = field(default_factory=list)


def _first(name):
    return name.split()[0].lower()


def resolve_owner(raw, attendees, known):
    """raw: owner text from the note. attendees: this meeting's attendee names.
    known: all known full names. See SPEC section 3."""
    tokens = raw.replace(".", ". ").split()
    if not tokens:
        return Resolution(None)
    first = tokens[0].lower()
    cands = sorted({p for p in known if _first(p) == first})
    if len(tokens) > 1:  # "Priya N." or "Priya Nair"
        rest = tokens[1].rstrip(".").lower()
        narrowed = []
        for p in cands:
            parts = p.split()
            last = parts[-1].lower() if len(parts) > 1 else ""
            if last.startswith(rest):
                narrowed.append(p)
        cands = narrowed
        if not cands:
            return Resolution(raw.strip())
    elif not cands:
        return Resolution(raw.strip().title())
    if len(cands) == 1:
        return Resolution(cands[0])
    present = [p for p in cands if p in set(attendees)]
    if len(present) == 1:
        return Resolution(present[0])
    return Resolution(None, True, present or cands)
