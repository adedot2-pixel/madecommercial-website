"""Generate a realistic, deliberately messy fake pipeline workbook for demos and tests.

All people, firms and email domains are fictional (emails use the reserved .example domain).
Dates are relative to `as_of` so the demo always looks current. Two files are produced:
the current sheet, and the same sheet as it looked a week earlier (to demo change tracking).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADERS = ["Contact", "Company", "E-mail", "Type", "Status", "Last touch", "Via", "Last move by",
           "Next step", "Next step date", "Owner", "Ticket", "Comments"]

# section, name, firm, type, stage, last (days before as_of), via, by, next step, next (days from as_of), owner, ticket, notes, extras
# extras: email=False/str, prev={...} (state a week earlier; "absent": True = not yet in sheet), date_style=..
R = dict
ROWS = [
    R(s="UK & IRELAND"),
    R(n="Charlotte Ashby", f="Harrowgate Pension Trust", t="Prospect", st="Mtg held", last=4, via="Meeting", by="Us",
      own="AH", tk="£40m", nt="Met at their offices with CIO. Interested in uncorrelated return stream; want to see risk reports."),
    R(n="Tom Whitlock", f="Harrowgate Pension Trust", t="prospect ", st="Met", last=4, via="mtg", by="us", own="AH",
      email=False, nt="Investment committee member, joined the meeting."),
    R(n="Priya Raman", f="Ellingham Family Office", t="Prospect", st="Deck sent", last=12, via="Email", by="We",
      own="AH", tk="$15m", nt="Sent deck + tear sheet. Principal travels a lot - try PA."),
    R(n="James O'Neill", f="Kilbrook Endowment", t="Prospect", st="Materials sent", last=20, via="Email", by="Us",
      own="JK", tk="€25m", nt="Old row - see below"),
    R(n="Hannah Leigh", f="St Aldric's College Fund", t="Prospect", st="soft circle", last=6, via="Call", by="Them",
      nx="Send sub docs", nd=-1, own="AH", tk="£10-15m", nt="Bursar keen to complete before year-end.",
      prev=R(nd=5)),
    R(n="Fiona Gallagher", f="Liffey Street Advisors", t="Consultant", st="Intro", last=45, via="Call", by="Us",
      own="JK", nt="Gatekeeper for several Irish schemes."),
    R(n="Oliver Pennington", f="Marlowe & Fitch Wealth", t="LP", st="Invested", last=20, via="Meeting", by="Us",
      own="AH", tk="$30m", nt="Quarterly review done."),
    R(n="Rachel Burrows", f="Thamesmead Insurance plc", t="Prospect", st="Hot", last=9, via="Email", by="Us",
      own="AH", tk="USD 50m", nt="Very warm after conference panel."),
    R(n=None, f="Brackley Partners", t="Prospect", st="Intro", last=None, via=None, by=None, own="JK",
      nt="Need a name - intro via Graham Ellis."),
    R(n="james o'neill", f="Kilbrook Endowment Ltd", t="Prospect", st="In DD", last=3, via="Email", by="Them",
      nx="Return DDQ answers", nd=3, own="JK", tk="€25m", nt="DDQ received - 40 questions, ops section heavy.",
      email="james.oneill@kilbrook-endowment.example", prev=R(st="Materials sent", last=20, nx=None, nd=None)),
    R(n="Zara Hussain", f="Pennine Health Pension", t="Prospect", st="Deck sent", last=16, via="e-mail", by="Us",
      nx="Chase for feedback", nd="TBC", own="JK", tk="£20m"),
    R(n="Owen Price", f="Severn Valley Council Pension", t="Prospect", st="Soft commit", last=9, via="Call", by="Us",
      own="AH", tk="£20m", nt="Waiting on committee date."),
    R(n="Paul Granger", f="Fenwick Trust", t="Prospect", st="Meeting held", last=1, via="Teams", by="Us",
      email="paul.granger at fenwick", own="AH", tk="$8m", prev=R(absent=True)),
    R(n="Ashby, Charlotte", f="Harrowgate Pension Trust", t="Prospect", st="Intro", last=40, via="Email", by="Us",
      own="SM", email="charlotte.ashby@harrowgate-pension-trust.example", nt="first approach"),

    R(s="NORDICS"),
    R(n="Henrik Solberg", f="Nordvik Kapital AS", t="Prospect", st="In DD", last=2, via="Meeting", by="Us",
      own="AH", tk="NOK 300m", nt="Onsite ODD visit done. They want references.",
      prev=R(st="Materials sent", last=9, via="Email")),
    R(n="Ingrid Lindqvist", f="Fjällsta Pensionsstiftelse", t="Prospect", st="Materials", last=33, via="Email",
      by="Us", own="JK", tk="SEK 250m"),
    R(n="Lars Ekdahl", f="Fjällsta Pensionsstiftelse", t="Prospect", st="Materials sent", last=10, via="Email",
      by="Them", nx="Call to discuss fee classes", nd=2, own="JK"),
    R(n="Mikkel Brandt", f="Østerlund Family Office", t="Prospect", st="Due Dilligence", last=8, via="Call",
      by="Client", own="AH", tk="$20m", nt="Asked for 3y monthly track record in Excel."),
    R(n="Aino Virtanen", f="Saimaa Mutual", t="Advisor", st="on hold", last=90, via="Email", by="Them", own="JK",
      nt="Revisit in 2027 - mandate frozen."),
    R(n="Sofie Dahl", f="Kattegat Asset Management", t="Prospect", st="Intro", last="last week", via="Call",
      by="Us", own="JK"),
    R(n="Clara Nyström", f="Kattegat Asset Management", t="Prospect", st="Intro", last=5, via="Call", by="us",
      own="JK", prev=R(absent=True)),
    R(n="Greta Holm", f="Saimaa Mutual", t="Consultant", st="Dormant", last=120, via="Email", by="Us", own="JK"),

    R(s="DACH & BENELUX"),
    R(n="Matthias Brenner", f="Alpenrand Stiftung", t="Prospect", st="Verbal", last=1, via="Call", by="Them",
      nx="Confirm allocation timing", nd=4, own="AH", tk="CHF 30m", nt="Verbal at CHF 30m, Jan dealing date likely.",
      prev=R(st="In DD", last=10)),
    R(n="Dr. Anja Keller", f="Alpenrand Stiftung", t="Prospect", st="verbal", last=1, via="Call", by="Them", own="AH"),
    R(n="Katrin Vogel", f="Rheinfels Versorgungswerk", t="Prospect", st="Meeting done", last=15, via="Meeting",
      by="Us", own="AH", tk="€40m", nt="Good meeting in Düsseldorf. Promised a note on liquidity terms."),
    R(n="Pieter de Vries", f="Zuiderhaven Pensioenfonds", t="Prospect", st="Intro", last=7, via="Email", by="Us",
      own="JK", tk="€100m"),
    R(n="Elise Janssens", f="Scheldt Capital", t="Consultant", st="Deck sent", last=52, via="Email", by="Us",
      own="JK"),
    R(n="Florian Huber", f="Wienerwald Family Office", t="Existing", st="Funded", last=14, via="Call", by="Us",
      own="AH", tk="€12m"),
    R(n="Lukas Steiner", f="Zugersee Partners AG", t="Prospect", st=None, last=11, via="Email", by="?", own="JK",
      tk="c.20m"),
    R(n="Marie Dubois", f="Lac Léman Gestion", t="Prospect", st="Meeting held", last=30, via="Lunch", by="Us",
      nx="Send quarterly letter", own="AH", tk="CHF 15m"),
    R(n="Ben Achterberg", f="Waddenzee Pensioen", t="Prospect", st="Materials sent", last=22, via="Email",
      by="Them", own="JK", tk="€30m", nt="Asked about capacity and lock-up."),

    R(s="FRANCE & SOUTHERN EUROPE"),
    R(n="Camille Laurent", f="Belvaux Patrimoine", t="Prospect", st="Materials sent", last=4, via="Email", by="Us",
      own="AH", tk="€10m"),
    R(n="Victor Lambert", f="Belvaux Patrimoine", t="Prospect", st="materials sent", last=4, via="Email", by="Us",
      own="AH", email=False),
    R(n="Giulia Romano", f="Fondazione Valdarno", t="Prospect", st="DD", last=18, via="Email", by="Them",
      own="AH", tk="€35m", nt="ODD call with COO pending - they sent follow-up questions.",
      prev=R(st="Materials sent")),
    R(n="Sophie Marchetti", f="Fondazione Valdarno", t="Prospect", st="DD", last=18, via="Email", by="Them",
      own="AH"),
    R(n="Alejandro Ruiz", f="Mirador Inversiones", t="Prospect", st="intro", last=25, via="Email", by="Us",
      own="JK", tk="$5m"),
    R(n="Inês Carvalho", f="Tejo Seguros", t="Prospect", st="Passed", last=70, via="Call", by="Them", own="JK",
      nt="Passed - too small an allocation for them this year."),
    R(n="Nikos Papadakis", f="Aegean Maritime Family Office", t="Prospect", st="1st meeting", last=9,
      via="Meeting", by="Us", own="AH", tk="$10m"),

    R(s="MIDDLE EAST & TURKEY"),
    R(n="Omar Al-Mansouri", f="Saffron Bay Holdings", t="Prospect", st="Soft circled", last=5, via="Meeting",
      by="Them", nx="Send side letter draft to legal", nd=1, own="AH", tk="$75m",
      nt="Wants MFN clause - legal to review.", prev=R(st="In DD", last=12, nx=None, nd=None)),
    R(n="Layla Haddad", f="Qasr Investment Authority", t="Prospect", st="Due diligence", last=12, via="Email",
      by="Us", own="AH", tk="$150m", nt="Sent full DDQ pack."),
    R(n="Noura Saleh", f="Qasr Investment Authority", t="Prospect", st="Due diligence", last=12, via="Email",
      by="Us", own="AH", email=False),
    R(n="Faisal Rahman", f="Dunes Endowment", t="Prospect", st="Intro", last=60, via="Meeting", by="Us",
      own="JK", tk="AED 50m"),
    R(n="Yusuf Kaya", f="Bosphorus Pension Fund", t="Prospect", st="Mtg held", last=3, via="Meeting", by="Us",
      own="AH", tk="$25m"),
    R(n="Ahmed Farouk", f="Nile Delta Partners", t="Prospect", st="Intro", last=19, via="Call", by="Us",
      own="JK", date_style="serial"),

    R(s="CONSULTANTS / EXISTING LPs"),
    R(n="Graham Ellis", f="Penrose Consulting", t="Consultant", st="Materials sent", last=14, via="Email",
      by="Us", nx="Quarterly update call", nd=9, own="AH"),
    R(n="Helen Cartwright", f="Bexley Investment Consulting", t="Consultant", st="Meeting held", last=40,
      via="Meeting", by="Us", own="AH", nt="Could put us on buy list for 3 clients."),
    R(n="Robert Lyle", f="Marlowe & Fitch Wealth", t="LP", st="Existing LP", last=100, via="Email", by="Us",
      own="AH", tk="$45m"),
    R(n="Siobhan Kerr", f="Atlantic Rim Pension", t="Existing", st="Invested", last=35, via="Call", by="Us",
      nx="Annual review meeting", nd=5, own="AH", tk="$60m"),
    R(n="Mark Feld", f="Hollin Capital", t="Prospect", st="Intro", last=2, via="Email", by="Them", own="JK",
      tk="250k", prev=R(absent=True)),
    R(n="Emma Stroud", f="Kestrel Lane Partners", t="Prospect", st="Intro", last=10, via="Email", by="Us",
      own="JK", tk="$10m"),
]

# Only in last week's version (deleted since)
PREV_ONLY = [
    R(sec="NORDICS", n="Peter Strand", f="Kattegat Asset Management", t="Prospect", st="Intro", last=30, via="Email",
      by="Us", own="JK"),
]

DATE_STYLES = ["datetime", "dmy", "d-mon-yy", "iso", "datetime", "mon-d-yyyy", "dmy-dots", "datetime", "d mon"]


def _slug(firm: str) -> str:
    f = re.sub(r"\b(AS|AG|plc|Ltd)\b", "", firm)
    f = (f.replace("ø", "o").replace("ä", "a").replace("é", "e").replace("ê", "e").replace("ö", "o")
         .replace("'", "").replace("&", "and"))
    return re.sub(r"[^a-z0-9]+", "-", f.lower()).strip("-")


def _email(row) -> str | None:
    if row.get("email") is False or not row.get("n"):
        return None
    if isinstance(row.get("email"), str):
        return row["email"]
    first, *rest = re.sub(r"^(Dr\.?)\s+", "", row["n"]).split()
    last = rest[-1] if rest else ""
    local = f"{first}.{last}".lower().replace("'", "").replace("ö", "o").replace("ê", "e")
    return f"{local}@{_slug(row['f'])}.example"


def _fmt_date(d: dt.date, style: str, as_of: dt.date):
    if style == "datetime":
        return dt.datetime(d.year, d.month, d.day)
    if style == "dmy":
        return d.strftime("%d/%m/%Y")
    if style == "d-mon-yy":
        return d.strftime("%d-%b-%y")
    if style == "iso":
        return d.isoformat()
    if style == "mon-d-yyyy":
        return d.strftime("%b %d, %Y")
    if style == "dmy-dots":
        return d.strftime("%d.%m.%Y")
    if style == "d mon":
        return f"{d.day} {d:%b}" if d.year == as_of.year else d.strftime("%d/%m/%Y")
    if style == "serial":
        return (d - dt.date(1899, 12, 30)).days
    return d.isoformat()


def _resolve(row: dict, prev: bool) -> dict | None:
    r = dict(row)
    if prev:
        p = row.get("prev") or {}
        if p.get("absent"):
            return None
        r.update({k: v for k, v in p.items()})
        # Anything contacted within the last week did not have that contact yet a week ago
        if "last" not in p and isinstance(r.get("last"), int) and r["last"] < 7:
            r["last"] = r["last"] + 9
            if "st" not in p and r.get("st") in ("Verbal", "verbal", "Mtg held", "Met", "Meeting held", "Soft circled"):
                r["st"] = "In DD" if r["st"].lower() in ("verbal", "soft circled") else "Intro"
    return r


def build(as_of: dt.date, prev: bool = False) -> Workbook:
    """prev=True builds the sheet as it looked 7 days before as_of (dates relative to as_of still)."""
    sheet_date = as_of - dt.timedelta(days=7) if prev else as_of
    wb = Workbook()
    ws = wb.active
    ws.title = "Pipeline"
    ncol = len(HEADERS)
    ws.cell(1, 1, "EMEA INVESTOR PIPELINE - CONFIDENTIAL").font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.cell(2, 1, f"Last updated by SM {sheet_date:%d/%m/%Y}")
    for i, h in enumerate(HEADERS, 1):
        c = ws.cell(4, i, h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDDDDD")
    row_no = 5
    style_i = 0
    rows = list(ROWS)
    if prev:
        for p in PREV_ONLY:  # insert under its section
            idx = next(i for i, r in enumerate(rows) if r.get("s") == p["sec"]) + 1
            rows.insert(idx, p)
    firm_run_start, last_firm = None, None

    def close_firm_run(end_row):
        if firm_run_start is not None and end_row > firm_run_start:
            ws.merge_cells(start_row=firm_run_start, start_column=2, end_row=end_row, end_column=2)
            ws.cell(firm_run_start, 2).alignment = Alignment(vertical="top")

    for raw in rows:
        if raw.get("s"):
            close_firm_run(row_no - 1)
            firm_run_start, last_firm = None, None
            row_no += 1  # blank spacer row
            ws.cell(row_no, 1, raw["s"]).font = Font(bold=True)
            ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
            row_no += 1
            continue
        r = _resolve(raw, prev)
        if r is None:
            continue
        style = r.get("date_style") or DATE_STYLES[style_i % len(DATE_STYLES)]
        style_i += 1
        last = r.get("last")
        if isinstance(last, int):
            last_v = _fmt_date(as_of - dt.timedelta(days=last), style, as_of)
        else:
            last_v = last
        nd = r.get("nd")
        nd_v = _fmt_date(as_of + dt.timedelta(days=nd), DATE_STYLES[(style_i + 3) % len(DATE_STYLES)], as_of) \
            if isinstance(nd, int) else nd
        vals = [r.get("n"), r.get("f"), _email(r), r.get("t"), r.get("st"), last_v, r.get("via"), r.get("by"),
                r.get("nx"), nd_v, r.get("own"), r.get("tk"), r.get("nt")]
        # Merge consecutive rows of the same firm, as EAs often do
        if r.get("f") and r.get("f") == last_firm:
            vals[1] = None
        else:
            close_firm_run(row_no - 1)
            firm_run_start, last_firm = row_no, r.get("f")
        for i, v in enumerate(vals, 1):
            if v is not None:
                cell = ws.cell(row_no, i, v)
                if isinstance(v, dt.datetime):
                    cell.number_format = "DD/MM/YYYY"
        row_no += 1
    close_firm_run(row_no - 1)
    for i, w in enumerate([22, 28, 36, 12, 16, 14, 10, 12, 30, 14, 7, 11, 60], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A5"
    return wb


def generate(out_dir: Path, as_of: dt.date) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cur = out_dir / "Pipeline.xlsx"
    prev = out_dir / "Pipeline_previous_week.xlsx"
    build(as_of).save(cur)
    build(as_of, prev=True).save(prev)
    return cur, prev
