"""Draft follow-up emails. Text only - this module (and the whole tool) never sends anything.

Template drafts are the default. An AI model can be switched on in the config
(drafts.ai.enabled); if it fails for any reason the template draft is used instead.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .rules import FollowUp

log = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "drafts"

COMPLIANCE_LINE = ("Review before sending. Do not add performance figures, forecasts or fund terms unless the "
                   "approved materials and a compliance sign-off cover them.")


@dataclass
class Draft:
    contact_id: str
    to: str | None
    subject: str
    body: str
    template: str
    source: str           # "template" or "ai:<provider>"
    reviewer_note: str

    def as_text(self) -> str:
        return (f"To: {self.to or '[no email address in sheet]'}\nSubject: {self.subject}\n\n{self.body}\n")


def choose_template(fu: FollowUp) -> str:
    c = fu.contact
    if fu.rule == "after_meeting":
        return "after_meeting"
    if fu.rule == "they_acted":
        return "reply"
    if fu.going_cold and fu.rule in (None, "we_acted", "unknown_actor"):
        return "reengage"
    stage_map = {"Intro": "nudge_intro", "Meeting held": "after_meeting", "Materials sent": "nudge_materials",
                 "Due diligence": "nudge_dd", "Soft commit": "nudge_soft_commit"}
    if c.investor_type == "existing_investor" and c.stage in (None, "Invested"):
        return "existing_investor"
    return stage_map.get(c.stage or "", "nudge_generic")


def _when(d: dt.date | None, as_of: dt.date) -> str:
    if not d:
        return "recently"
    days = (as_of - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7 and d.weekday() < as_of.weekday():
        return f"on {d:%A}"
    if days < 14:
        return "last week"
    return f"on {d.day} {d:%B}"


class Drafter:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined,
                               keep_trailing_newline=False, trim_blocks=True, lstrip_blocks=True)
        self.ai = cfg["drafts"]["ai"]

    def context(self, fu: FollowUp, as_of: dt.date) -> dict:
        c, d = fu.contact, self.cfg["drafts"]
        return {
            "first_name": c.first_name or "there", "firm": c.firm or "your team", "stage": c.stage,
            "last_contact_when": _when(c.last_contact_date, as_of),
            "last_contact_type": c.last_contact_type or "conversation",
            "met": c.last_contact_type == "meeting",
            "next_action": c.next_action, "sender_name": d["sender_name"], "sender_title": d["sender_title"],
            "fund_name": d["fund_name"], "sign_off": d["sign_off"], "investor_type": c.investor_type,
        }

    def template_draft(self, fu: FollowUp, as_of: dt.date) -> Draft:
        name = choose_template(fu)
        raw = self.env.get_template(f"{name}.txt.j2").render(**self.context(fu, as_of)).strip()
        subject, _, body = raw.partition("\n")
        return Draft(fu.contact.contact_id, fu.contact.email, subject.removeprefix("Subject:").strip(),
                     body.strip(), name, "template", self.reviewer_note(fu))

    def reviewer_note(self, fu: FollowUp) -> str:
        c = fu.contact
        parts = [f"Why: {fu.reason or 'no due date'}"]
        if c.next_action:
            parts.append(f"Next action in sheet: {c.next_action}")
        if c.notes:
            parts.append(f"Sheet notes: {c.notes}")
        for n in fu.tool_notes:
            parts.append(f"Tool note ({n['created_by']}, {n['created_at'][:10]}): {n['note']}")
        parts.append(COMPLIANCE_LINE)
        return "\n".join(parts)

    def draft(self, fu: FollowUp, as_of: dt.date) -> Draft:
        base = self.template_draft(fu, as_of)
        if not self.ai.get("enabled"):
            return base
        try:
            body = self._ai_body(fu, as_of, base)
            if body:
                base.body, base.source = body.strip(), f"ai:{self.ai['provider']}"
        except Exception as e:  # never let the model break the daily run
            log.warning("AI drafting failed for %s, using template: %s", fu.contact.contact_id, e)
        return base

    # ---- optional AI ----
    def _prompt(self, fu: FollowUp, as_of: dt.date, base: Draft) -> tuple[str, str]:
        c = fu.contact
        system = (
            "You draft short, professional follow-up emails for the Head of EMEA investor relations at a hedge fund. "
            "British English. 60-120 words. No performance figures, returns, forecasts, fees or fund terms. "
            "No promises. Do not invent facts, meetings, documents or dates that are not in the facts given. "
            "Return only the email body (greeting to sign-off), no subject line."
        )
        facts = {
            "recipient_first_name": c.first_name, "firm": c.firm, "investor_type": c.investor_type,
            "stage": c.stage, "last_contact": _when(c.last_contact_date, as_of),
            "last_contact_type": c.last_contact_type, "who_acted_last": c.last_actor,
            "why_follow_up_is_due": fu.reason, "next_action": c.next_action,
            "sender": f"{self.cfg['drafts']['sender_name']}, {self.cfg['drafts']['sender_title']}",
            "fund": self.cfg["drafts"]["fund_name"],
        }
        if self.ai.get("send_notes") and c.notes:
            facts["notes"] = c.notes
        user = ("Facts (JSON):\n" + json.dumps(facts, indent=1, default=str) +
                "\n\nA template version for reference (improve on it, keep it as short):\n" + base.body)
        return system, user

    def _ai_body(self, fu: FollowUp, as_of: dt.date, base: Draft) -> str | None:
        system, user = self._prompt(fu, as_of, base)
        if self.ai["provider"] == "ollama":
            payload = {"model": self.ai.get("model") or "llama3.1:8b", "system": system, "prompt": user,
                       "stream": False, "options": {"temperature": 0.3}}
            req = urllib.request.Request(self.ai.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
                                         data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())["response"]
        if self.ai["provider"] == "anthropic":
            import anthropic  # optional dependency: pip install anthropic

            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
            resp = client.beta.messages.create(
                model=self.ai.get("model") or "claude-opus-5-5",
                max_tokens=2000,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if resp.stop_reason == "refusal":
                return None
            return "".join(b.text for b in resp.content if b.type == "text") or None
        return None
