"""Turn raw spreadsheet rows into clean Contact records (dates, stages, tickets, duplicates)."""
from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import re
from dataclasses import dataclass, field

from .config import STANDARD_STAGES
from .ingest import SheetData

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
CURRENCY_CODES = {"USD", "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "AED", "SAR", "JPY", "QAR", "KWD", "CAD", "AUD"}
FIRM_SUFFIXES = r"\b(ltd|limited|llp|plc|ag|sa|gmbh|ab|asa|as|bv|nv|spa|srl|sarl|inc|llc|lp|co)\b\.?"


def _key(s: str | None) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def firm_key(firm: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(FIRM_SUFFIXES, " ", _key(firm))).strip()


def name_key(name: str | None) -> str:
    n = (name or "").strip()
    if "," in n:  # "Smith, John" -> "John Smith"
        last, _, first = n.partition(",")
        n = f"{first} {last}"
    n = re.sub(r"^(mr|mrs|ms|miss|dr|prof|sir|dame)\.?\s+", "", n.strip(), flags=re.I)
    return _key(n)


def make_contact_id(name: str | None, firm: str | None) -> str:
    raw = f"{name_key(name)}|{firm_key(firm)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class Contact:
    contact_id: str
    source_rows: list[int]
    name: str | None = None
    firm: str | None = None
    email: str | None = None
    investor_type: str = "unknown"
    stage: str | None = None
    stage_raw: str | None = None
    last_contact_date: dt.date | None = None
    last_contact_type: str | None = None
    last_actor: str = "unknown"
    next_action: str | None = None
    next_action_date: dt.date | None = None
    owner: str | None = None
    ticket_raw: str | None = None
    ticket_amount: float | None = None
    ticket_currency: str | None = None
    ticket_base: float | None = None
    notes: str | None = None
    issues: list[dict] = field(default_factory=list)  # {"field", "msg", "gap": bool}

    def issue(self, fld: str, msg: str, gap: bool = True):
        self.issues.append({"field": fld, "msg": msg, "gap": gap})

    @property
    def display_name(self) -> str:
        return self.name or "(no name)"

    @property
    def first_name(self) -> str:
        n = (self.name or "").strip()
        if "," in n:
            n = n.partition(",")[2].strip()
        n = re.sub(r"^(mr|mrs|ms|miss|dr|prof|sir|dame)\.?\s+", "", n, flags=re.I)
        return n.split()[0].capitalize() if n else ""


# ---------- value parsers ----------

def is_blank(v, cfg) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() in {b.lower() for b in cfg["values"]["blanks"]}
    return False


def clean_text(v) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def parse_date(v, cfg, as_of: dt.date) -> tuple[dt.date | None, str | None]:
    """Return (date, problem). Problem is None if parsed or genuinely blank."""
    if is_blank(v, cfg):
        return None, None
    if isinstance(v, dt.datetime):
        return v.date(), None
    if isinstance(v, dt.date):
        return v, None
    if isinstance(v, (int, float)):
        if 20000 < v < 80000:  # Excel serial date stored as a number
            return dt.date(1899, 12, 30) + dt.timedelta(days=int(v)), None
        return None, f"'{v}' is not a date"
    s = str(v).strip()
    s_clean = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=re.I).replace(",", " ")
    s_clean = re.sub(r"\s+", " ", s_clean).strip()
    for fmt in cfg["values"]["date_formats"]:
        try:
            return dt.datetime.strptime(s_clean, fmt).date(), None
        except ValueError:
            pass
    # Year-less forms: "12 Oct", "Oct 12", "12/10"
    for fmt in ("%d %b", "%d %B", "%b %d", "%B %d", "%d/%m" if cfg["values"].get("day_first", True) else "%m/%d"):
        try:
            d = dt.datetime.strptime(f"{s_clean} {as_of.year}", f"{fmt} %Y").date()
            return d, f"'{s}' has no year - assumed {d.year}"
        except ValueError:
            pass
    for fmt in ("%b %d %Y", "%B %d %Y", "%d %b %y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s_clean, fmt).date(), None
        except ValueError:
            pass
    return None, f"could not read date '{s}'"


class AliasMapper:
    def __init__(self, table: dict[str, list[str]]):
        self.lookup = {}
        for canon, aliases in table.items():
            self.lookup[_key(canon)] = canon
            for a in aliases or []:
                self.lookup[_key(a)] = canon

    def map(self, v) -> tuple[str | None, str]:
        k = _key(str(v)) if v is not None else ""
        if not k:
            return None, "blank"
        if k in self.lookup:
            return self.lookup[k], "exact"
        close = difflib.get_close_matches(k, self.lookup.keys(), n=1, cutoff=0.84)
        if close:
            return self.lookup[close[0]], "fuzzy"
        # a recognised word inside a longer phrase, e.g. "intro call" / "materials sent 3/11"
        for alias in sorted(self.lookup, key=len, reverse=True):
            if len(alias) >= 4 and re.search(rf"\b{re.escape(alias)}\b", k):
                return self.lookup[alias], "fuzzy"
        return None, "unknown"


class StageMapper(AliasMapper):
    def __init__(self, cfg):
        table = {s: [] for s in STANDARD_STAGES}
        for s, aliases in (cfg.get("stages") or {}).items():
            table[s] = list(aliases or [])
        super().__init__(table)


def parse_ticket(v, cfg) -> tuple[float | None, str | None, str | None]:
    """'$25m' -> (25e6, 'USD', None); '€10-15m' -> (12.5e6, 'EUR', note)."""
    if is_blank(v, cfg):
        return None, None, None
    t = cfg["tickets"]
    if isinstance(v, (int, float)):
        return float(v) * (t["default_unit"] if v < 10000 else 1), t["default_currency"], None
    s = str(v).strip()
    low = s.lower().replace(",", "")
    cur = next((c for sym, c in CURRENCY_SYMBOLS.items() if sym in s), None)
    if not cur:
        cur = next((c for c in CURRENCY_CODES if re.search(rf"\b{c.lower()}\b", low)), None)
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", low)]
    if not nums:
        return None, None, f"could not read ticket size '{s}'"
    note = None
    if len(nums) >= 2 and re.search(r"\d\s*(-|–|to)\s*\d", low):
        amount = (nums[0] + nums[1]) / 2
        note = f"ticket range '{s}' - used midpoint"
    else:
        amount = nums[0]
    if re.search(r"\d\s*(bn|b|billion)\b", low):
        mult = 1e9
    elif re.search(r"\d\s*(m|mm|mn|mil|million)\b", low):
        mult = 1e6
    elif re.search(r"\d\s*(k|thousand)\b", low):
        mult = 1e3
    else:
        mult = t["default_unit"] if amount < 10000 else 1
    return amount * mult, cur or t["default_currency"], note


def to_base(amount: float | None, currency: str | None, cfg) -> tuple[float | None, str | None]:
    if amount is None:
        return None, None
    rates = cfg["tickets"]["fx_to_base"]
    if currency not in rates:
        return None, f"no FX rate for {currency} in config (tickets.fx_to_base)"
    return amount * float(rates[currency]), None


# ---------- row -> Contact ----------

def build_contacts(sheet: SheetData, colmap: dict[str, int], cfg: dict, as_of: dt.date) -> tuple[list[Contact], list[dict]]:
    """Returns (contacts, rejected_rows). Rejected rows have neither name nor firm."""
    stage_m = StageMapper(cfg)
    vals = cfg["values"]
    type_m = AliasMapper(vals["investor_type"])
    ctype_m = AliasMapper(vals["last_contact_type"])
    actor_m = AliasMapper(vals["last_actor"])
    flip = vals.get("last_actor_column_means", "acted_last") == "whose_turn"

    contacts, rejected = [], []
    for row_no, raw in sheet.rows:
        def get(f):
            i = colmap.get(f)
            return raw[i] if i is not None and i < len(raw) else None

        name = clean_text(get("name")) if not is_blank(get("name"), cfg) else None
        firm = clean_text(get("firm")) if not is_blank(get("firm"), cfg) else None
        if not name and not firm:
            rejected.append({"row": row_no, "msg": "row has data but no contact name or firm"})
            continue
        c = Contact(contact_id=make_contact_id(name, firm), source_rows=[row_no], name=name, firm=firm)
        if not name:
            c.issue("name", "no contact name")
        if not firm:
            c.issue("firm", "no firm")

        email = get("email")
        if not is_blank(email, cfg):
            e = str(email).strip().lower().removeprefix("mailto:")
            if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e):
                c.email = e
            else:
                c.issue("email", f"email '{email}' does not look valid")

        if "investor_type" in colmap and not is_blank(get("investor_type"), cfg):
            t, how = type_m.map(get("investor_type"))
            c.investor_type = t or "unknown"
            if not t:
                c.issue("investor_type", f"unknown type '{get('investor_type')}'", gap=False)

        raw_stage = get("stage")
        if not is_blank(raw_stage, cfg):
            c.stage_raw = clean_text(raw_stage)
            st, how = stage_m.map(raw_stage)
            c.stage = st
            if not st:
                c.issue("stage", f"stage '{c.stage_raw}' not recognised - add it to 'stages' in the config")
            elif how == "fuzzy" and _key(c.stage_raw) not in stage_m.lookup:
                c.issue("stage", f"stage '{c.stage_raw}' read as '{st}' (close match - add it to the config to confirm)", gap=False)
        else:
            c.issue("stage", "no stage")

        for f in ("last_contact_date", "next_action_date"):
            d, prob = parse_date(get(f), cfg, as_of)
            if d and prob and "no year" in prob and f == "last_contact_date" and d > as_of:
                d = d.replace(year=d.year - 1)  # "14 Dec" seen in January is last December
                prob = prob.rsplit(" ", 1)[0] + f" {d.year}"
            setattr(c, f, d)
            if prob:
                c.issue(f, prob, gap=d is None)
        if c.next_action_date and c.next_action_date.year < 2000:
            c.issue("next_action_date", "implausible date", gap=True)
            c.next_action_date = None
        if c.last_contact_date and c.last_contact_date > as_of:
            # A future "last contact" is usually a typo, or a meeting booked ahead
            c.issue("last_contact_date", f"last contact {c.last_contact_date:%d %b %Y} is in the future", gap=True)
        if not c.last_contact_date and not c.next_action_date:
            c.issue("last_contact_date", "no last contact date and no next action date")

        if not is_blank(get("last_contact_type"), cfg):
            ct, _ = ctype_m.map(get("last_contact_type"))
            c.last_contact_type = ct or "other"
        if not is_blank(get("last_actor"), cfg):
            a, _ = actor_m.map(get("last_actor"))
            if a and flip:
                a = "them" if a == "us" else "us"
            c.last_actor = a or "unknown"
            if not a:
                c.issue("last_actor", f"'{get('last_actor')}' not understood as us/them", gap=False)

        c.next_action = clean_text(get("next_action")) if not is_blank(get("next_action"), cfg) else None
        c.owner = clean_text(get("owner")) if not is_blank(get("owner"), cfg) else None
        c.notes = clean_text(get("notes")) if not is_blank(get("notes"), cfg) else None

        tr = get("ticket_size")
        if not is_blank(tr, cfg):
            c.ticket_raw = clean_text(tr)
            amt, cur, note = parse_ticket(tr, cfg)
            c.ticket_amount, c.ticket_currency = amt, cur
            if note:
                c.issue("ticket_size", note, gap=amt is None)
            base, prob = to_base(amt, cur, cfg)
            c.ticket_base = base
            if prob:
                c.issue("ticket_size", prob, gap=False)
        contacts.append(c)
    return dedupe(contacts), rejected


def _merge_into(keep: Contact, other: Contact):
    for f in ("email", "stage", "stage_raw", "last_contact_date", "last_contact_type", "next_action",
              "next_action_date", "owner", "ticket_raw", "ticket_amount", "ticket_currency", "ticket_base",
              "notes", "firm", "name"):
        if getattr(keep, f) in (None, "") and getattr(other, f) not in (None, ""):
            setattr(keep, f, getattr(other, f))
    if keep.name and other.name and keep.name == keep.name.lower() and other.name != other.name.lower():
        keep.name = other.name  # prefer the properly capitalised spelling
    if keep.last_actor == "unknown":
        keep.last_actor = other.last_actor
    if keep.investor_type == "unknown":
        keep.investor_type = other.investor_type


def dedupe(contacts: list[Contact]) -> list[Contact]:
    """Same person = same normalised name+firm, or same email. Keep the most recently contacted
    row (ties: the lower row, i.e. most recently added), fill its blanks from the others, and flag."""
    groups: list[list[Contact]] = []
    by_id: dict[str, int] = {}
    by_email: dict[str, int] = {}
    for c in contacts:
        gi = by_id.get(c.contact_id)
        if gi is None and c.email:
            gi = by_email.get(c.email)
        if gi is None:
            gi = len(groups)
            groups.append([])
        groups[gi].append(c)
        by_id[c.contact_id] = gi
        if c.email:
            by_email[c.email] = gi
    out = []
    for g in groups:
        if len(g) == 1:
            out.append(g[0])
            continue
        g.sort(key=lambda c: (c.last_contact_date or dt.date.min, c.source_rows[0]), reverse=True)
        keep = g[0]
        kept_row = keep.source_rows[0]
        for other in g[1:]:
            _merge_into(keep, other)
        rows = sorted(r for c in g for r in c.source_rows)
        keep.source_rows = rows
        seen, merged_issues = set(), []
        for c in g:
            for i in c.issues:
                k = (i["field"], i["msg"])
                if k in seen:
                    continue
                seen.add(k)
                # drop "missing X" problems that the merge has now filled
                if i["msg"].startswith("no ") and i["field"] in ("stage", "name", "firm") and getattr(keep, i["field"]):
                    continue
                if i["field"] == "last_contact_date" and i["msg"].startswith("no last contact") and \
                        (keep.last_contact_date or keep.next_action_date):
                    continue
                merged_issues.append(i)
        keep.issues = merged_issues
        keep.issue("duplicate", f"appears {len(g)} times (rows {', '.join(map(str, rows))}) - "
                   f"using row {kept_row} (most recent contact); remove the other row(s)", gap=True)
        out.append(keep)
    return out
