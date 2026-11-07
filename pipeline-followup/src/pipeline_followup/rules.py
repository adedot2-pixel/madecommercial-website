"""Follow-up rules, working-day calendar and priority score."""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import statistics
from dataclasses import dataclass, field

from .normalise import Contact

# England & Wales bank holidays (gov.uk). Extend via rules.extra_holidays.
UK_BANK_HOLIDAYS = {
    dt.date(2025, 1, 1), dt.date(2025, 4, 18), dt.date(2025, 4, 21), dt.date(2025, 5, 5),
    dt.date(2025, 5, 26), dt.date(2025, 8, 25), dt.date(2025, 12, 25), dt.date(2025, 12, 26),
    dt.date(2026, 1, 1), dt.date(2026, 4, 3), dt.date(2026, 4, 6), dt.date(2026, 5, 4),
    dt.date(2026, 5, 25), dt.date(2026, 8, 31), dt.date(2026, 12, 25), dt.date(2026, 12, 28),
    dt.date(2027, 1, 1), dt.date(2027, 3, 26), dt.date(2027, 3, 29), dt.date(2027, 5, 3),
    dt.date(2027, 5, 31), dt.date(2027, 8, 30), dt.date(2027, 12, 27), dt.date(2027, 12, 28),
}
UK_CALENDAR_LAST_YEAR = 2027


class Calendar:
    def __init__(self, cfg: dict):
        r = cfg["rules"]
        self.holidays = set(UK_BANK_HOLIDAYS) if str(r.get("working_calendar", "UK")).upper() == "UK" else set()
        for d in r.get("extra_holidays") or []:
            self.holidays.add(d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)))

    def is_working(self, d: dt.date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def add_working_days(self, d: dt.date, n: int) -> dt.date:
        while n > 0:
            d += dt.timedelta(days=1)
            if self.is_working(d):
                n -= 1
        return d

    def add(self, d: dt.date, days: int, working: bool) -> dt.date:
        return self.add_working_days(d, days) if working else d + dt.timedelta(days=days)


def week_window(as_of: dt.date) -> tuple[dt.date, dt.date]:
    """Mon-Fri of the current week; at the weekend, the coming week."""
    monday = as_of - dt.timedelta(days=as_of.weekday())
    if as_of.weekday() >= 5:
        monday += dt.timedelta(days=7)
    return monday, monday + dt.timedelta(days=4)


@dataclass
class FollowUp:
    contact: Contact
    due_date: dt.date | None = None
    rule: str | None = None             # explicit / after_meeting / they_acted / we_acted / unknown_actor
    reason: str = ""
    bucket: str = "none"                # overdue / this_week / upcoming / later / none
    days_overdue: int = 0
    days_since_contact: int | None = None
    going_cold: bool = False
    excluded: bool = False
    status: str = "open"                # open / snoozed / done
    snooze_until: dt.date | None = None
    priority: int = 0
    breakdown: dict = field(default_factory=dict)
    tool_notes: list[dict] = field(default_factory=list)
    basis: str = ""                     # fingerprint of the sheet facts behind this follow-up

    @property
    def actionable(self) -> bool:
        return not self.excluded and self.status == "open" and self.due_date is not None


def basis_of(c: Contact) -> str:
    raw = "|".join(str(x) for x in (c.stage, c.last_contact_date, c.last_actor, c.last_contact_type,
                                     c.next_action_date, c.next_action))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _fmt(d: dt.date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def evaluate_contact(c: Contact, cfg: dict, cal: Calendar, as_of: dt.date) -> FollowUp:
    r = cfg["rules"]
    fu = FollowUp(contact=c, basis=basis_of(c))
    if c.last_contact_date:
        fu.days_since_contact = (as_of - c.last_contact_date).days
    if c.stage in (r.get("excluded_stages") or []):
        fu.excluded = True
        return fu
    if c.stage is None and not r.get("include_unknown_stage", True):
        fu.excluded = True
        return fu

    candidates: list[tuple[dt.date, str, str]] = []
    if r.get("explicit_next_action", True) and c.next_action_date:
        what = f": {c.next_action}" if c.next_action else ""
        candidates.append((c.next_action_date, "explicit", f"Next action date set ({_fmt(c.next_action_date)}){what}"))
    elif c.last_contact_date:
        lcd = c.last_contact_date
        met = c.last_contact_type == "meeting" or (c.last_contact_type is None and c.stage == "Meeting held")
        if met:
            n = int(r["after_meeting_working_days"])
            candidates.append((cal.add_working_days(lcd, n), "after_meeting",
                               f"Met on {_fmt(lcd)}, nothing logged since - follow up within {n} working days"))
        if c.last_actor == "them":
            k = r["they_acted_last"]
            candidates.append((cal.add(lcd, int(k["days"]), bool(k["working_days"])), "they_acted",
                               f"They came back on {_fmt(lcd)} - reply due within {k['days']}"
                               f"{' working' if k['working_days'] else ''} days"))
        elif c.last_actor == "us" and not met:
            k = r["we_acted_last"]
            candidates.append((cal.add(lcd, int(k["days"]), bool(k["working_days"])), "we_acted",
                               f"We last reached out on {_fmt(lcd)}, no response logged - nudge after {k['days']} days"))
        elif c.last_actor == "unknown" and not met:
            k = r["unknown_actor"]
            candidates.append((cal.add(lcd, int(k["days"]), bool(k["working_days"])), "unknown_actor",
                               f"Last contact {_fmt(lcd)} (who acted last not recorded) - check in after {k['days']} days"))
    if candidates:
        fu.due_date, fu.rule, fu.reason = min(candidates, key=lambda x: x[0])
    if fu.days_since_contact is not None and fu.days_since_contact >= int(r["going_cold_days"]):
        fu.going_cold = True
    _bucket(fu, cfg, as_of)
    return fu


def _bucket(fu: FollowUp, cfg: dict, as_of: dt.date):
    if fu.due_date is None:
        fu.bucket = "none"
        return
    mon, fri = week_window(as_of)
    if fu.due_date < as_of:
        fu.bucket = "overdue"
        fu.days_overdue = (as_of - fu.due_date).days
    elif fu.due_date <= fri:
        fu.bucket = "this_week"
    elif fu.due_date <= as_of + dt.timedelta(days=int(cfg["digest"].get("show_upcoming_days", 14))):
        fu.bucket = "upcoming"
    else:
        fu.bucket = "later"


def score_all(fus: list[FollowUp], cfg: dict, as_of: dt.date) -> None:
    p = cfg["priority"]
    w = p["weights"]
    cap = max(1, int(p["overdue_cap_days"]))
    tickets = [f.contact.ticket_base for f in fus if f.contact.ticket_base and not f.excluded]
    tmax = max(tickets) if tickets else None
    tfill = statistics.median(tickets) if tickets and p.get("missing_ticket", "median") == "median" else 0.0
    for f in fus:
        if f.excluded:
            continue
        if f.bucket == "overdue":
            urg = 0.5 + 0.5 * min(f.days_overdue, cap) / cap
        elif f.bucket == "this_week":
            urg = 0.45 if f.due_date == as_of else 0.3
        elif f.bucket == "upcoming":
            urg = 0.15
        elif f.bucket == "later":
            urg = 0.05
        else:
            urg = 0.2  # no due date at all (usually a data gap)
        if f.going_cold:
            urg = min(1.0, urg + float(p.get("going_cold_bonus", 0.15)))
        sw = p["stage_weight"]
        stg = float(sw.get(f.contact.stage or "unknown", sw.get("unknown", 0.3)))
        tv = f.contact.ticket_base if f.contact.ticket_base else tfill
        tk = (math.log1p(tv / 1e6) / math.log1p(tmax / 1e6)) if tmax and tv else 0.0
        parts = {"urgency": urg * w["urgency"], "stage": stg * w["stage"], "ticket": min(1.0, tk) * w["ticket"]}
        f.breakdown = {k: round(v, 1) for k, v in parts.items()}
        f.breakdown["ticket_estimated"] = not bool(f.contact.ticket_base)
        f.priority = int(round(sum(parts.values())))
