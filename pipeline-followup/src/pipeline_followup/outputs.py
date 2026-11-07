"""Write the run's outputs: digest.html, digest.eml (unsent), drafts.txt, followups.xlsx."""
from __future__ import annotations

import datetime as dt
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from openpyxl.utils import get_column_letter

from .config import stage_display
from .drafts import Draft
from .engine import Result, this_week_label

TEMPLATES = Path(__file__).resolve().parent / "templates"


def fmt_date(d) -> str:
    return f"{d.day} {d:%b %Y}" if d else ""


def fmt_m(v) -> str:
    if not v:
        return "-"
    if v >= 1e9:
        return f"{v / 1e9:,.2f}bn"
    return f"{v / 1e6:,.1f}m"


def render_digest(r: Result, cfg: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    t = cfg["tickets"]
    fx = ", ".join(f"{k} {v}" for k, v in t["fx_to_base"].items() if k != t["base_currency"])
    return env.get_template("digest.html.j2").render(
        r=r, as_of=r.as_of, source_name=r.sheet.path.name, sheet_name=r.sheet.sheet_name,
        n_contacts=len(r.contacts), generated=dt.datetime.now().strftime("%d %b %Y %H:%M"),
        week_label=this_week_label(r.as_of), cold_days=cfg["rules"]["going_cold_days"],
        summary=r.pipeline_summary(cfg), base_ccy=t["base_currency"], fx_note=f"1 unit = x {t['base_currency']}: {fx}",
        upcoming_days=cfg["digest"].get("show_upcoming_days", 14),
        d=fmt_date, m=fmt_m, stage=lambda s: stage_display(cfg, s))


def write_eml(html: str, r: Result, cfg: dict, path: Path):
    """An *unsent* message. `X-Unsent: 1` makes Outlook open it as a draft to review and send manually."""
    msg = EmailMessage()
    msg["To"] = ", ".join(cfg["digest"].get("to") or [])
    msg["Subject"] = (f"Follow-ups {r.as_of:%a} {r.as_of.day} {r.as_of:%b}: {len(r.overdue)} overdue, "
                      f"{len(r.due_this_week)} due this week, {len(r.going_cold)} going cold")
    msg["Date"] = formatdate(localtime=True)
    msg["X-Unsent"] = "1"
    msg.set_content("This digest is HTML. Open digest.html if it does not display.")
    msg.add_alternative(html, subtype="html")
    path.write_bytes(bytes(msg))


def write_drafts_txt(drafts: list[tuple], path: Path, as_of: dt.date):
    lines = [f"DRAFT FOLLOW-UP EMAILS - {as_of:%A} {as_of.day} {as_of:%B %Y}",
             "Copy-ready drafts. NOTHING HAS BEEN SENT. Review every draft before sending.", ""]
    for i, (fu, d) in enumerate(drafts, 1):
        c = fu.contact
        lines += ["=" * 78,
                  f"{i}. {c.display_name} - {c.firm or ''}  |  priority {fu.priority}  |  due {fmt_date(fu.due_date)}"
                  f"{' (' + str(fu.days_overdue) + 'd overdue)' if fu.days_overdue else ''}",
                  "-" * 78, "[Reviewer note - not part of the email]"]
        lines += ["  " + ln for ln in d.reviewer_note.splitlines()]
        lines += [f"  Draft source: {d.source} ({d.template})", "-" * 78, d.as_text()]
    if not drafts:
        lines.append("No follow-ups due.")
    path.write_text("\n".join(lines), encoding="utf-8")


def followup_rows(r: Result, cfg: dict, drafts: dict[str, Draft] | None = None) -> list[dict]:
    rows = []
    for f in sorted(r.followups, key=lambda f: (f.excluded, f.status != "open", -f.priority)):
        c = f.contact
        rows.append({
            "Priority": None if f.excluded else f.priority,
            "Status": "excluded" if f.excluded else f.status,
            "Bucket": {"overdue": "Overdue", "this_week": "Due this week", "upcoming": "Upcoming",
                       "later": "Later", "none": "No due date"}[f.bucket] if not f.excluded else "",
            "Contact": c.name, "Firm": c.firm, "Email": c.email, "Type": c.investor_type,
            "Stage": stage_display(cfg, c.stage) if c.stage else "", "Stage (as typed)": c.stage_raw,
            "Last contact": c.last_contact_date, "Days since": f.days_since_contact,
            "Last contact type": c.last_contact_type, "Who acted last": c.last_actor,
            "Next action": c.next_action, "Due date": f.due_date, "Days overdue": f.days_overdue or None,
            "Going cold": "yes" if f.going_cold else "", "Why": f.reason, "Owner": c.owner,
            "Ticket (as typed)": c.ticket_raw, "Ticket currency": c.ticket_currency,
            f"Ticket ({cfg['tickets']['base_currency']}m)": round(c.ticket_base / 1e6, 1) if c.ticket_base else None,
            "Snoozed until": f.snooze_until, "Excel row(s)": ", ".join(map(str, c.source_rows)),
            "Data issues": "; ".join(i["msg"] for i in c.issues),
            "Draft subject": drafts[c.contact_id].subject if drafts and c.contact_id in drafts else None,
            "Draft body": drafts[c.contact_id].body if drafts and c.contact_id in drafts else None,
        })
    return rows


def write_excel(r: Result, cfg: dict, drafts: dict[str, Draft], path: Path):
    sheets = {
        "Follow-ups": pd.DataFrame(followup_rows(r, cfg, drafts)),
        "Data gaps": pd.DataFrame([{"Excel row(s)": ", ".join(map(str, f.contact.source_rows)), "Contact": f.contact.name,
                                    "Firm": f.contact.firm, "Problem": "; ".join(g["msg"] for g in gaps)}
                                   for f, gaps in r.data_gaps] +
                                  [{"Excel row(s)": str(x["row"]), "Problem": x["msg"]} for x in r.rejected_rows]),
        "Changes": pd.DataFrame([{"Change": ch["label"], "Contact": ch["who"], "Detail": ch["detail"]} for ch in r.changes]),
        "Pipeline by stage": pd.DataFrame([{"Stage": s["stage"], "Contacts": s["count"],
                                            f"Potential ({cfg['tickets']['base_currency']}m)": round(s["value"] / 1e6, 1),
                                            "Sized": s["with_ticket"],
                                            "By currency": ", ".join(f"{k} {fmt_m(v)}" for k, v in s["by_ccy"].items())}
                                           for s in r.pipeline_summary(cfg)]),
    }
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            if df.empty:
                df = pd.DataFrame({"": ["(none)"]})
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200) if v is not None])
                ws.column_dimensions[get_column_letter(i)].width = min(60, max(8, width + 2))
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    if isinstance(cell.value, (dt.date, dt.datetime)):
                        cell.number_format = "DD-MMM-YYYY"
