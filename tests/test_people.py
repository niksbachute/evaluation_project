from actiontrack.people import resolve_owner

KNOWN = {"Priya Nair", "Priya Shah", "Rahul Mehta", "Rahul Verma", "Sam Okafor"}


def test_unique_first_name():
    assert resolve_owner("Sam", [], KNOWN).owner == "Sam Okafor"


def test_attendees_disambiguate():
    assert resolve_owner("Priya", ["Priya Shah", "Sam Okafor"], KNOWN).owner == "Priya Shah"


def test_both_present_is_ambiguous():
    r = resolve_owner("Priya", ["Priya Nair", "Priya Shah"], KNOWN)
    assert r.owner is None and r.ambiguous and r.candidates == ["Priya Nair", "Priya Shah"]


def test_no_attendees_is_ambiguous():
    assert resolve_owner("Rahul", [], KNOWN).ambiguous


def test_initial_and_full_name():
    assert resolve_owner("Priya N.", [], KNOWN).owner == "Priya Nair"
    assert resolve_owner("Rahul Verma", [], KNOWN).owner == "Rahul Verma"


def test_unknown_person_kept():
    r = resolve_owner("zed", [], KNOWN)
    assert r.owner == "Zed" and not r.ambiguous
