"""Tool-side state in SQLite: run log, minimal snapshots, change log, snooze/done/notes.

Never written back to the spreadsheet. Designed to sit on a shared drive: rollback-journal mode
(WAL does not work on network shares), short transactions and a generous busy timeout.
"""
from __future__ import annotations

import datetime as dt
import getpass
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    as_of TEXT NOT NULL,
    source_path TEXT,
    source_sha256 TEXT,
    rows_read INTEGER,
    contacts INTEGER,
    followups_due INTEGER,
    warnings INTEGER,
    status TEXT,
    run_by TEXT,
    tool_version TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    contact_id TEXT NOT NULL,
    data TEXT NOT NULL,              -- JSON: name, firm, stage, dates, ticket (no notes, no email)
    PRIMARY KEY (run_id, contact_id)
);
CREATE TABLE IF NOT EXISTS changes (
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    contact_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- new / removed / stage_move / went_quiet / reactivated / next_action_changed
    detail TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- snooze / done / note
    created_at TEXT NOT NULL,
    created_by TEXT,
    snooze_until TEXT,
    basis TEXT,                      -- for 'done': the sheet facts it applied to
    note TEXT,
    undone_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_actions_contact ON actions(contact_id);
"""


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=20)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("PRAGMA busy_timeout=20000")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- runs ----
    def start_run(self, as_of: dt.date, source: str, version: str) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO runs(started_at, as_of, source_path, status, run_by, tool_version) VALUES (?,?,?,?,?,?)",
                (dt.datetime.now().isoformat(timespec="seconds"), as_of.isoformat(), source, "running",
                 current_user(), version))
            return cur.lastrowid

    def finish_run(self, run_id: int, **kw):
        kw["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        cols = ", ".join(f"{k}=?" for k in kw)
        with self.conn() as c:
            c.execute(f"UPDATE runs SET {cols} WHERE run_id=?", (*kw.values(), run_id))

    def last_runs(self, n=10) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT ?", (n,))]

    # ---- snapshots / changes ----
    def save_snapshot(self, run_id: int, rows: dict[str, dict]):
        with self.conn() as c:
            c.executemany("INSERT OR REPLACE INTO snapshots(run_id, contact_id, data) VALUES (?,?,?)",
                          [(run_id, cid, json.dumps(d, default=str)) for cid, d in rows.items()])

    def previous_snapshot(self, before_run_id: int, as_of: dt.date | None = None) -> tuple[dict | None, dict]:
        """Latest successful run before this one (and not later than as_of) -> (run row, {cid: data})."""
        q = "SELECT * FROM runs WHERE run_id < ? AND status='ok'"
        args: list = [before_run_id]
        if as_of:
            q += " AND as_of <= ?"
            args.append(as_of.isoformat())
        q += " ORDER BY as_of DESC, run_id DESC LIMIT 1"
        with self.conn() as c:
            run = c.execute(q, args).fetchone()
            if not run:
                return None, {}
            rows = c.execute("SELECT contact_id, data FROM snapshots WHERE run_id=?", (run["run_id"],))
            return dict(run), {r["contact_id"]: json.loads(r["data"]) for r in rows}

    def save_changes(self, run_id: int, changes: list[dict]):
        with self.conn() as c:
            c.executemany("INSERT INTO changes(run_id, contact_id, kind, detail) VALUES (?,?,?,?)",
                          [(run_id, ch["contact_id"], ch["kind"], ch["detail"]) for ch in changes])

    def purge_snapshots(self, retention_days: int):
        cutoff = (dt.date.today() - dt.timedelta(days=retention_days)).isoformat()
        with self.conn() as c:
            old = [r[0] for r in c.execute("SELECT run_id FROM runs WHERE as_of < ?", (cutoff,))]
            # always keep the most recent run, whatever its age
            latest = c.execute("SELECT MAX(run_id) FROM runs WHERE status='ok'").fetchone()[0]
            old = [r for r in old if r != latest]
            c.executemany("DELETE FROM snapshots WHERE run_id=?", [(r,) for r in old])

    # ---- actions ----
    def add_action(self, contact_id: str, kind: str, *, snooze_until: dt.date | None = None,
                   basis: str | None = None, note: str | None = None, user: str | None = None) -> int:
        if kind not in ("snooze", "done", "note"):
            raise ValueError("kind must be snooze/done/note")
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO actions(contact_id, kind, created_at, created_by, snooze_until, basis, note) "
                "VALUES (?,?,?,?,?,?,?)",
                (contact_id, kind, dt.datetime.now().isoformat(timespec="seconds"), user or current_user(),
                 snooze_until.isoformat() if snooze_until else None, basis, note))
            return cur.lastrowid

    def reassign_actions(self, old_id: str, new_id: str) -> int:
        """Carry snooze/done/notes over when a contact's key changes (rename, firm move)."""
        with self.conn() as c:
            return c.execute("UPDATE actions SET contact_id=? WHERE contact_id=?", (new_id, old_id)).rowcount

    def undo_action(self, action_id: int):
        with self.conn() as c:
            c.execute("UPDATE actions SET undone_at=? WHERE id=?",
                      (dt.datetime.now().isoformat(timespec="seconds"), action_id))

    def actions(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        with self.conn() as c:
            for r in c.execute("SELECT * FROM actions WHERE undone_at IS NULL ORDER BY created_at"):
                out.setdefault(r["contact_id"], []).append(dict(r))
        return out
