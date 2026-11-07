"""The daily run: read -> evaluate -> compare -> draft -> write outputs -> snapshot -> log."""
from __future__ import annotations

import datetime as dt
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .changes import compare, snapshot_row
from .config import resolve_path
from .drafts import Drafter
from .engine import Result, evaluate
from .outputs import render_digest, write_drafts_txt, write_eml, write_excel
from .state import State

log = logging.getLogger("pipeline_followup")


def setup_logging(cfg: dict, verbose: bool = False) -> Path:
    path = resolve_path(cfg, cfg["state"]["log"])
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("pipeline_followup")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        fh = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(sh)
    return path


def open_state(cfg: dict) -> State:
    return State(resolve_path(cfg, cfg["state"]["db"]))


def run(cfg: dict, as_of: dt.date | None = None) -> tuple[Result, Path]:
    as_of = as_of or dt.date.today()
    setup_logging(cfg)
    state = open_state(cfg)
    src = resolve_path(cfg, cfg["source"]["path"])
    run_id = state.start_run(as_of, str(src), __version__)
    # The log records counts and file fingerprints only - no names, emails or notes.
    log.info("run %s started: as_of=%s source=%s", run_id, as_of, src.name)
    try:
        r = evaluate(cfg, as_of, state)
        prev_run, prev = state.previous_snapshot(run_id, as_of)
        r.previous_run = prev_run
        r.changes = compare(prev_run, prev, r.contacts, as_of, int(cfg["rules"]["going_cold_days"]),
                            cfg["rules"].get("excluded_stages") or [])

        drafter = Drafter(cfg)
        due = r.due_now
        drafts = [(f, drafter.draft(f, as_of)) for f in due]
        by_id = {f.contact.contact_id: d for f, d in drafts}

        out_dir = resolve_path(cfg, cfg["output"]["dir"]) / as_of.isoformat()
        out_dir.mkdir(parents=True, exist_ok=True)
        html = render_digest(r, cfg)
        (out_dir / "digest.html").write_text(html, encoding="utf-8")
        if cfg["digest"].get("write_eml", True):
            write_eml(html, r, cfg, out_dir / "digest.eml")
        write_drafts_txt(drafts, out_dir / "drafts.txt", as_of)
        if cfg["output"].get("excel_export", True):
            write_excel(r, cfg, by_id, out_dir / "followups.xlsx")

        state.save_snapshot(run_id, {c.contact_id: snapshot_row(c) for c in r.contacts})
        state.save_changes(run_id, r.changes)
        state.purge_snapshots(int(cfg["state"].get("snapshot_retention_days", 120)))
        for w in r.warnings:
            log.warning(w)
        msg = (f"rows={len(r.sheet.rows)} contacts={len(r.contacts)} overdue={len(r.overdue)} "
               f"this_week={len(r.due_this_week)} cold={len(r.going_cold)} gaps={len(r.data_gaps)} "
               f"changes={len(r.changes)} drafts={len(drafts)} sha256={r.sheet.sha256[:16]}")
        state.finish_run(run_id, status="ok", source_sha256=r.sheet.sha256, rows_read=len(r.sheet.rows),
                         contacts=len(r.contacts), followups_due=len(due), warnings=len(r.warnings), message=msg)
        log.info("run %s ok: %s -> %s", run_id, msg, out_dir)
        return r, out_dir
    except Exception as e:
        state.finish_run(run_id, status="failed", message=f"{type(e).__name__}: {e}"[:500])
        log.error("run %s failed: %s: %s", run_id, type(e).__name__, e)
        raise
