"""Compare this run with the previous snapshot."""
from __future__ import annotations

import datetime as dt

from .config import STANDARD_STAGES
from .normalise import Contact

KIND_LABEL = {
    "new": "New contact",
    "removed": "No longer in sheet",
    "stage_move": "Stage moved",
    "went_quiet": "Went quiet",
    "activity": "New activity logged",
    "next_action_changed": "Next action date changed",
    "ticket_changed": "Ticket size changed",
}


def snapshot_row(c: Contact) -> dict:
    """Minimal fields kept between runs. Deliberately excludes notes and email addresses."""
    return {
        "name": c.name, "firm": c.firm, "stage": c.stage,
        "last_contact_date": c.last_contact_date.isoformat() if c.last_contact_date else None,
        "next_action_date": c.next_action_date.isoformat() if c.next_action_date else None,
        "ticket_base": round(c.ticket_base) if c.ticket_base else None,
    }


def _d(s):
    return dt.date.fromisoformat(s) if s else None


def compare(prev_run: dict | None, prev: dict[str, dict], contacts: list[Contact], as_of: dt.date,
            cold_days: int, excluded_stages=()) -> list[dict]:
    if prev_run is None:
        return []
    prev_as_of = dt.date.fromisoformat(prev_run["as_of"])
    out = []
    cur = {c.contact_id: c for c in contacts}

    def who(c=None, p=None):
        name = (c.name if c else p.get("name")) or "(no name)"
        firm = (c.firm if c else p.get("firm")) or ""
        return f"{name} ({firm})" if firm else name

    for cid, c in cur.items():
        p = prev.get(cid)
        if p is None:
            out.append({"contact_id": cid, "kind": "new", "who": who(c),
                        "detail": f"added at stage {c.stage or '(none)'}"})
            continue
        if p.get("stage") != c.stage:
            a, b = p.get("stage") or "(none)", c.stage or "(none)"
            direction = ""
            if p.get("stage") in STANDARD_STAGES and c.stage in STANDARD_STAGES:
                direction = " (forward)" if STANDARD_STAGES.index(c.stage) > STANDARD_STAGES.index(p["stage"]) else " (back)"
            out.append({"contact_id": cid, "kind": "stage_move", "who": who(c), "detail": f"{a} -> {b}{direction}"})
        plcd, lcd = _d(p.get("last_contact_date")), c.last_contact_date
        if lcd and plcd and lcd > plcd:
            out.append({"contact_id": cid, "kind": "activity", "who": who(c),
                        "detail": f"last contact {plcd:%d %b} -> {lcd:%d %b}"})
        if lcd and c.stage not in excluded_stages:
            was = (prev_as_of - lcd).days if not plcd or plcd == lcd else (prev_as_of - plcd).days
            now = (as_of - lcd).days
            if now >= cold_days > was:
                out.append({"contact_id": cid, "kind": "went_quiet", "who": who(c),
                            "detail": f"no contact for {now} days (since {lcd:%d %b})"})
        if p.get("next_action_date") != (c.next_action_date.isoformat() if c.next_action_date else None):
            a = p.get("next_action_date") or "none"
            b = c.next_action_date.isoformat() if c.next_action_date else "none"
            out.append({"contact_id": cid, "kind": "next_action_changed", "who": who(c), "detail": f"{a} -> {b}"})
        pt, t = p.get("ticket_base"), round(c.ticket_base) if c.ticket_base else None
        if pt != t and (pt or t):
            out.append({"contact_id": cid, "kind": "ticket_changed", "who": who(c),
                        "detail": f"{_m(pt)} -> {_m(t)}"})
    for cid, p in prev.items():
        if cid not in cur:
            out.append({"contact_id": cid, "kind": "removed", "who": who(p=p), "detail": "row deleted or renamed"})
    order = list(KIND_LABEL)
    out.sort(key=lambda x: (order.index(x["kind"]), x["who"]))
    for ch in out:
        ch["label"] = KIND_LABEL[ch["kind"]]
    return out


def _m(v):
    return f"{v / 1e6:,.0f}m" if v else "none"
