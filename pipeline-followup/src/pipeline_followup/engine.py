"""Core evaluation: sheet -> contacts -> follow-ups (+ tool-side state). Shared by `run` and the dashboard."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from .config import STANDARD_STAGES, resolve_path, stage_display
from .ingest import SheetData, read_sheet, resolve_columns
from .normalise import Contact, build_contacts
from .rules import Calendar, FollowUp, UK_CALENDAR_LAST_YEAR, evaluate_contact, score_all, week_window
from .state import State


@dataclass
class Result:
    as_of: dt.date
    sheet: SheetData
    colmap: dict
    unresolved_columns: dict
    contacts: list[Contact]
    followups: list[FollowUp]
    rejected_rows: list[dict]
    warnings: list[str] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    previous_run: dict | None = None

    # ---- digest sections ----
    def _open(self):
        return [f for f in self.followups if not f.excluded and f.status == "open"]

    @property
    def overdue(self):
        return sorted([f for f in self._open() if f.bucket == "overdue"], key=lambda f: -f.priority)

    @property
    def due_this_week(self):
        return sorted([f for f in self._open() if f.bucket == "this_week"], key=lambda f: (f.due_date, -f.priority))

    @property
    def upcoming(self):
        return sorted([f for f in self._open() if f.bucket == "upcoming"], key=lambda f: f.due_date)

    @property
    def going_cold(self):
        return sorted([f for f in self.followups if not f.excluded and f.going_cold and f.status != "done"],
                      key=lambda f: -(f.days_since_contact or 0))

    @property
    def snoozed(self):
        return [f for f in self.followups if f.status == "snoozed"]

    @property
    def due_now(self):
        """Everything that should get a draft today: overdue + due this week."""
        return self.overdue + self.due_this_week

    @property
    def data_gaps(self):
        rows = []
        for f in self.followups:
            gaps = [i for i in f.contact.issues if i["gap"]]
            # For Invested/Dormant only a missing/unknown stage matters
            if f.excluded:
                gaps = [i for i in gaps if i["field"] == "duplicate"]
            if gaps:
                rows.append((f, gaps))
        rows.sort(key=lambda x: x[0].contact.source_rows[0])
        return rows

    @property
    def notices(self):
        """Non-blocking interpretation notes (fuzzy stage matches, assumed years, ranges)."""
        return [(f, [i for i in f.contact.issues if not i["gap"]]) for f in self.followups
                if any(not i["gap"] for i in f.contact.issues)]

    def pipeline_summary(self, cfg: dict) -> list[dict]:
        by = defaultdict(lambda: {"count": 0, "value": 0.0, "with_ticket": 0, "by_ccy": defaultdict(float)})
        for c in self.contacts:
            k = c.stage or "(no stage)"
            by[k]["count"] += 1
            if c.ticket_base:
                by[k]["value"] += c.ticket_base
                by[k]["with_ticket"] += 1
            if c.ticket_amount and c.ticket_currency:
                by[k]["by_ccy"][c.ticket_currency] += c.ticket_amount
        order = STANDARD_STAGES + ["(no stage)"]
        out = []
        for s in order:
            if s in by:
                d = by[s]
                out.append({"stage": stage_display(cfg, s) if s in STANDARD_STAGES else s, "count": d["count"],
                            "value": d["value"], "with_ticket": d["with_ticket"],
                            "by_ccy": dict(sorted(d["by_ccy"].items()))})
        return out


def evaluate(cfg: dict, as_of: dt.date, state: State | None = None) -> Result:
    path = resolve_path(cfg, cfg["source"]["path"])
    sheet = read_sheet(path, cfg)
    colmap, unresolved = resolve_columns(sheet, cfg)
    warnings = []
    for f in ("name", "firm"):
        if f not in colmap:
            raise ValueError(f"Required column for '{f}' not found. Looked for: {unresolved.get(f) or '(not configured)'}. "
                             f"Headers in sheet: {', '.join(h for h in sheet.headers if h)}. Run `inspect` to fix the mapping.")
    for f, cands in unresolved.items():
        warnings.append(f"Column for '{f}' not found (looked for {', '.join(cands)}) - field treated as empty")
    if as_of.year > UK_CALENDAR_LAST_YEAR and str(cfg["rules"].get("working_calendar")).upper() == "UK":
        warnings.append(f"Built-in UK bank holidays end in {UK_CALENDAR_LAST_YEAR}; add later ones to rules.extra_holidays")

    contacts, rejected = build_contacts(sheet, colmap, cfg, as_of)
    cal = Calendar(cfg)
    fus = [evaluate_contact(c, cfg, cal, as_of) for c in contacts]
    if state is not None:
        apply_actions(fus, state, as_of)
    score_all(fus, cfg, as_of)
    return Result(as_of=as_of, sheet=sheet, colmap=colmap, unresolved_columns=unresolved, contacts=contacts,
                  followups=fus, rejected_rows=rejected, warnings=warnings)


def apply_actions(fus: list[FollowUp], state: State, as_of: dt.date):
    acts = state.actions()
    for f in fus:
        for a in acts.get(f.contact.contact_id, []):
            if a["kind"] == "note":
                f.tool_notes.append(a)
            elif a["kind"] == "snooze" and a["snooze_until"]:
                until = dt.date.fromisoformat(a["snooze_until"])
                if until > as_of:
                    f.status, f.snooze_until = "snoozed", until
            elif a["kind"] == "done":
                # 'Done' holds only while the sheet facts are unchanged; new activity in the sheet resurfaces it.
                if a["basis"] == f.basis:
                    f.status = "done"
                    f.snooze_until = None


def this_week_label(as_of: dt.date) -> str:
    mon, fri = week_window(as_of)
    return f"{mon.day} {mon:%b} - {fri.day} {fri:%b}"
