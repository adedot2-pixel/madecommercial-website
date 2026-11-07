import datetime as dt
import hashlib
from pathlib import Path

import openpyxl
import pytest

from pipeline_followup.config import DEFAULT_CONFIG_FILE, load_config
from pipeline_followup.dummy import generate
from pipeline_followup.engine import evaluate
from pipeline_followup.ingest import read_sheet
from pipeline_followup.mapping import suggest_mapping
from pipeline_followup.normalise import Contact, StageMapper, dedupe, make_contact_id, parse_date, parse_ticket
from pipeline_followup.rules import Calendar, evaluate_contact, week_window
from pipeline_followup.runner import run
from pipeline_followup.state import State

AS_OF = dt.date(2026, 11, 7)  # a Saturday
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg():
    return load_config(None)


def contact(**kw):
    c = Contact(contact_id=make_contact_id(kw.get("name", "A B"), kw.get("firm", "F")), source_rows=[5],
                name="A B", firm="F")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_example_config_matches_packaged_defaults():
    assert (ROOT / "config" / "config.example.yaml").read_text() == DEFAULT_CONFIG_FILE.read_text()


@pytest.mark.parametrize("raw,expected", [
    ("03/11/2026", dt.date(2026, 11, 3)),      # day-first
    ("3-Nov-26", dt.date(2026, 11, 3)),
    ("2026-11-03", dt.date(2026, 11, 3)),
    ("Nov 03, 2026", dt.date(2026, 11, 3)),
    ("03.11.2026", dt.date(2026, 11, 3)),
    ("3rd November 2026", dt.date(2026, 11, 3)),
    (46329, dt.date(2026, 11, 3)),               # Excel serial number
    (dt.datetime(2026, 11, 3, 0, 0), dt.date(2026, 11, 3)),
])
def test_parse_date(cfg, raw, expected):
    d, _ = parse_date(raw, cfg, AS_OF)
    assert d == expected


def test_parse_date_blank_and_bad(cfg):
    assert parse_date("TBC", cfg, AS_OF) == (None, None)
    d, prob = parse_date("last week", cfg, AS_OF)
    assert d is None and "could not read" in prob


@pytest.mark.parametrize("raw,amount,ccy", [
    ("$25m", 25e6, "USD"), ("€10-15m", 12.5e6, "EUR"), ("£5mm", 5e6, "GBP"), ("CHF 30m", 30e6, "CHF"),
    ("25", 25e6, "USD"), ("1.2bn", 1.2e9, "USD"), ("250k", 250e3, "USD"), ("c.20m", 20e6, "USD"),
])
def test_parse_ticket(cfg, raw, amount, ccy):
    a, c, _ = parse_ticket(raw, cfg)
    assert a == pytest.approx(amount) and c == ccy


@pytest.mark.parametrize("typed,stage", [
    ("Mtg held", "Meeting held"), ("DDQ", "Due diligence"), ("Due Dilligence", "Due diligence"),
    ("soft circle", "Soft commit"), ("Funded", "Invested"), ("on hold", "Dormant"), ("Hot", None),
])
def test_stage_mapping(cfg, typed, stage):
    assert StageMapper(cfg).map(typed)[0] == stage


def test_working_days_skip_weekend_and_bank_holiday(cfg):
    cal = Calendar(cfg)
    assert cal.add_working_days(dt.date(2026, 11, 5), 2) == dt.date(2026, 11, 9)   # Thu -> Mon
    assert cal.add_working_days(dt.date(2026, 12, 23), 2) == dt.date(2026, 12, 29)  # over Christmas + 28th


def test_week_window_at_weekend():
    assert week_window(AS_OF) == (dt.date(2026, 11, 9), dt.date(2026, 11, 13))
    assert week_window(dt.date(2026, 11, 11)) == (dt.date(2026, 11, 9), dt.date(2026, 11, 13))


def test_rules(cfg):
    cal = Calendar(cfg)
    met = evaluate_contact(contact(stage="Meeting held", last_contact_date=dt.date(2026, 11, 5),
                                   last_contact_type="meeting", last_actor="us"), cfg, cal, AS_OF)
    assert met.rule == "after_meeting" and met.due_date == dt.date(2026, 11, 9) and met.bucket == "this_week"
    us = evaluate_contact(contact(stage="Intro", last_contact_date=dt.date(2026, 10, 20), last_actor="us",
                                  last_contact_type="email"), cfg, cal, AS_OF)
    assert us.rule == "we_acted" and us.due_date == dt.date(2026, 10, 30) and us.bucket == "overdue"
    them = evaluate_contact(contact(stage="Due diligence", last_contact_date=dt.date(2026, 11, 6),
                                    last_actor="them", last_contact_type="email"), cfg, cal, AS_OF)
    assert them.due_date == dt.date(2026, 11, 11)  # 3 working days
    explicit = evaluate_contact(contact(stage="Intro", last_contact_date=dt.date(2026, 11, 6), last_actor="them",
                                        next_action_date=dt.date(2026, 11, 20)), cfg, cal, AS_OF)
    assert explicit.rule == "explicit" and explicit.due_date == dt.date(2026, 11, 20)
    cold = evaluate_contact(contact(stage="Intro", last_contact_date=dt.date(2026, 9, 1), last_actor="us"),
                            cfg, cal, AS_OF)
    assert cold.going_cold
    inv = evaluate_contact(contact(stage="Invested", last_contact_date=dt.date(2026, 1, 1)), cfg, cal, AS_OF)
    assert inv.excluded and inv.due_date is None


def test_dedupe_keeps_most_recent_and_flags():
    a = contact(name="James O'Neill", firm="Kilbrook Endowment", last_contact_date=dt.date(2026, 10, 1),
                email="j@k.example", stage="Materials sent")
    b = contact(name="james o'neill", firm="Kilbrook Endowment Ltd", last_contact_date=dt.date(2026, 11, 1),
                stage="Due diligence")
    b.contact_id = make_contact_id(b.name, b.firm)
    assert a.contact_id == b.contact_id  # case and "Ltd" ignored
    out = dedupe([a, b])
    assert len(out) == 1
    k = out[0]
    assert k.stage == "Due diligence" and k.email == "j@k.example" and k.name == "James O'Neill"
    assert any(i["field"] == "duplicate" for i in k.issues)


def test_suggest_mapping_on_renamed_headers(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Investor Name", "Organisation", "Mail", "Pipeline Stage", "Date of last contact", "Follow up date",
               "Size", "Remarks"])
    ws.append(["Ann Lee", "Foo Pension", "ann@foo.example", "Intro", "01/11/2026", "10/11/2026", "$10m",
               "Long free-text remark about the investor and their plans"])
    ws.append(["Bob Ray", "Bar Fund", "bob@bar.example", "DD", "02/11/2026", None, "€5m", "Another long remark here"])
    p = tmp_path / "x.xlsx"
    wb.save(p)
    cfg = load_config(None)
    m = suggest_mapping(read_sheet(p, cfg))
    assert m["name"]["header"] == "Investor Name"
    assert m["firm"]["header"] == "Organisation"
    assert m["email"]["header"] == "Mail"
    assert m["stage"]["header"] == "Pipeline Stage"
    assert m["last_contact_date"]["header"] == "Date of last contact"
    assert m["next_action_date"]["header"] == "Follow up date"
    assert m["ticket_size"]["header"] == "Size"


def test_demo_end_to_end_is_read_only(tmp_path):
    cur, prev = generate(tmp_path, AS_OF)
    before = hashlib.sha256(cur.read_bytes()).hexdigest(), cur.stat().st_mtime_ns
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text('source: {path: "Pipeline.xlsx"}\nstate: {db: "s.db", log: "r.log"}\noutput: {dir: "out"}\n')
    cfg = load_config(cfg_file)
    cfg["source"]["path"] = str(prev)
    run(cfg, AS_OF - dt.timedelta(days=7))
    cfg = load_config(cfg_file)
    r, out = run(cfg, AS_OF)
    assert (hashlib.sha256(cur.read_bytes()).hexdigest(), cur.stat().st_mtime_ns) == before
    for f in ("digest.html", "digest.eml", "drafts.txt", "followups.xlsx"):
        assert (out / f).exists()
    assert r.overdue and r.due_this_week and r.going_cold and r.data_gaps
    kinds = {c["kind"] for c in r.changes}
    assert {"new", "removed", "stage_move", "went_quiet"} <= kinds
    eml = (out / "digest.eml").read_text()
    assert "X-Unsent: 1" in eml
    # sections headings and merged firm cells were handled
    names = {c.name for c in r.contacts}
    assert "Tom Whitlock" in names and "NORDICS" not in names
    tom = next(c for c in r.contacts if c.name == "Tom Whitlock")
    assert tom.firm == "Harrowgate Pension Trust"


def test_actions_snooze_done_resurface(tmp_path, cfg):
    cur, _ = generate(tmp_path, AS_OF)
    cfg["source"]["path"] = str(cur)
    st = State(tmp_path / "s.db")
    r = evaluate(cfg, AS_OF, st)
    f = r.overdue[0]
    st.add_action(f.contact.contact_id, "snooze", snooze_until=AS_OF + dt.timedelta(days=7))
    r2 = evaluate(cfg, AS_OF, st)
    assert f.contact.contact_id not in {x.contact.contact_id for x in r2.overdue}
    # snooze expires
    r3 = evaluate(cfg, AS_OF + dt.timedelta(days=8), st)
    assert next(x for x in r3.followups if x.contact.contact_id == f.contact.contact_id).status == "open"
    # done holds while the sheet facts are unchanged ...
    g = r.overdue[1]
    st.add_action(g.contact.contact_id, "done", basis=g.basis)
    assert next(x for x in evaluate(cfg, AS_OF, st).followups if x.contact.contact_id == g.contact.contact_id).status == "done"
    # ... and a different basis (sheet updated) resurfaces it
    st2 = State(tmp_path / "s2.db")
    st2.add_action(g.contact.contact_id, "done", basis="old-basis")
    assert next(x for x in evaluate(cfg, AS_OF, st2).followups if x.contact.contact_id == g.contact.contact_id).status == "open"
