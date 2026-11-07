"""Suggest a header -> field mapping for an unfamiliar sheet (used by `inspect`)."""
from __future__ import annotations

import datetime as dt
import difflib
import re

from .config import FIELDS, KEY_FIELDS, REQUIRED_FIELDS, STANDARD_STAGES
from .ingest import SheetData, norm_header

FIELD_ALIASES: dict[str, list[str]] = {
    "name": ["contact", "contact name", "name", "investor name", "person", "full name", "key contact"],
    "firm": ["firm", "company", "organisation", "organization", "institution", "investor", "account", "entity"],
    "email": ["email", "e-mail", "email address", "mail"],
    "investor_type": ["type", "investor type", "category", "client type", "segment"],
    "stage": ["stage", "status", "pipeline stage", "phase"],
    "last_contact_date": ["last contact", "last contact date", "last touch", "last spoke", "date of last contact", "last meeting"],
    "last_contact_type": ["last contact type", "contact type", "via", "channel", "method", "medium"],
    "last_actor": ["who acted last", "last actor", "last move by", "ball in court", "waiting on", "with whom"],
    "next_action": ["next action", "next step", "next steps", "action", "to do", "follow up"],
    "next_action_date": ["next action date", "next step date", "follow up date", "due date", "action date", "chase date"],
    "owner": ["owner", "coverage", "rm", "relationship manager", "lead"],
    "ticket_size": ["ticket", "ticket size", "potential ticket", "size", "amount", "aum", "allocation", "commitment"],
    "notes": ["notes", "comments", "comment", "remarks", "update", "latest"],
}


def _score_header(header: str, field: str) -> float:
    h = norm_header(header)
    best = 0.0
    for a in FIELD_ALIASES[field]:
        if h == a:
            return 1.0
        if re.search(rf"\b{re.escape(a)}\b", h):
            best = max(best, 0.8 if len(a) > 3 else 0.6)
        best = max(best, difflib.SequenceMatcher(None, h, a).ratio() * 0.75)
    return best


def _content_profile(values: list) -> dict:
    vals = [v for v in values if v is not None and str(v).strip()]
    n = len(vals) or 1
    emails = sum(1 for v in vals if isinstance(v, str) and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v.strip()))
    dates = sum(1 for v in vals if isinstance(v, (dt.date, dt.datetime))
                or (isinstance(v, str) and re.search(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}[ -][A-Za-z]{3}", v)))
    money = sum(1 for v in vals if isinstance(v, str) and re.search(r"[$€£]|\d\s*(m|mm|bn|k)\b|usd|eur|gbp|chf", v.lower()))
    return {"filled": len(vals), "email": emails / n, "date": dates / n, "money": money / n,
            "avg_len": sum(len(str(v)) for v in vals) / n}


def suggest_mapping(sheet: SheetData) -> dict[str, dict]:
    """Return field -> {header, confidence, why}. Greedy best-first assignment."""
    cols = [(i, h) for i, h in enumerate(sheet.headers) if h]
    profiles = {i: _content_profile([r[i] for _, r in sheet.rows]) for i, _ in cols}
    scored = []
    for i, h in cols:
        p = profiles[i]
        for f in FIELDS:
            s = _score_header(h, f)
            why = "header name"
            if f == "email" and p["email"] > 0.5:
                s, why = max(s, 0.95), "values look like email addresses"
            if f in ("last_contact_date", "next_action_date") and p["date"] < 0.3 and s < 1:
                s *= 0.6
            if f == "ticket_size" and p["money"] > 0.3:
                s, why = max(s, 0.7), "values look like amounts"
            if f == "notes" and p["avg_len"] > 25:
                s = max(s, 0.5)
            if s >= 0.45:
                scored.append((s, f, i, h, why))
    scored.sort(reverse=True)
    out, used_cols = {}, set()
    for s, f, i, h, why in scored:
        if f in out or i in used_cols:
            continue
        out[f] = {"header": h, "confidence": round(s, 2), "why": why}
        used_cols.add(i)
    return out


def missing_fields(mapping: dict) -> dict[str, list[str]]:
    return {
        "required": [f for f in REQUIRED_FIELDS if f not in mapping],
        "key": [f for f in KEY_FIELDS if f not in mapping],
        "optional": [f for f in FIELDS if f not in mapping and f not in REQUIRED_FIELDS and f not in KEY_FIELDS],
    }


def suggest_stage_aliases(values: list[str], cfg: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Map distinct typed stage values onto standard stages. Returns (additions, unmatched)."""
    from .normalise import StageMapper

    mapper = StageMapper(cfg)
    additions: dict[str, list[str]] = {s: [] for s in STANDARD_STAGES}
    unmatched = []
    for v in sorted({str(x).strip() for x in values if x is not None and str(x).strip()}):
        stage, how = mapper.map(v)
        if stage and how == "fuzzy":
            additions[stage].append(v.lower())
        elif not stage:
            unmatched.append(v)
    return {k: v for k, v in additions.items() if v}, unmatched
