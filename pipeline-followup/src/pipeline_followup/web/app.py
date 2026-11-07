"""Local dashboard. Binds to 127.0.0.1 only. Actions are written to the tool's SQLite file, never to the sheet."""
from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from ..config import stage_display
from ..drafts import Drafter
from ..engine import evaluate, this_week_label
from ..outputs import write_excel
from ..runner import open_state

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
BUCKET_LABEL = {"overdue": "Overdue", "this_week": "This week", "upcoming": "Upcoming", "later": "Later",
                "none": "No due date"}


class ActionIn(BaseModel):
    contact_id: str = Field(min_length=6, max_length=40)
    kind: str
    days: int | None = Field(default=None, ge=1, le=365)
    until: dt.date | None = None
    note: str | None = Field(default=None, max_length=4000)
    basis: str | None = Field(default=None, max_length=40)


def create_app(cfg: dict, as_of: dt.date | None = None) -> FastAPI:
    app = FastAPI(title="Pipeline follow-ups", docs_url=None, redoc_url=None, openapi_url=None)
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    state = open_state(cfg)
    drafter = Drafter(cfg)
    allowed_hosts = {f"{h}:{cfg['dashboard']['port']}" for h in ("127.0.0.1", "localhost")} | {"127.0.0.1", "localhost"}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Defends against DNS-rebinding / cross-site requests to the local server
        host = request.headers.get("host", "")
        if host.split(":")[0] not in ("127.0.0.1", "localhost") and host not in allowed_hosts:
            return JSONResponse({"error": "local access only"}, status_code=403)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1].split(":")[0] not in ("127.0.0.1", "localhost"):
                return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
            if "application/json" not in request.headers.get("content-type", ""):
                return JSONResponse({"error": "JSON only"}, status_code=415)
        return await call_next(request)

    def today() -> dt.date:
        return as_of or dt.date.today()

    def rows_payload():
        r = evaluate(cfg, today(), state)
        rows = []
        for f in r.followups:
            c = f.contact
            draft = drafter.template_draft(f, today()) if not f.excluded and f.due_date else None
            rows.append({
                "id": c.contact_id, "contact": c.display_name, "firm": c.firm or "", "email": c.email or "",
                "stage": stage_display(cfg, c.stage) if c.stage else "", "stage_raw": c.stage_raw or "",
                "last_contact": c.last_contact_date.isoformat() if c.last_contact_date else "",
                "last_type": c.last_contact_type or "", "last_actor": c.last_actor,
                "days_since": f.days_since_contact, "next_action": c.next_action or "",
                "due": f.due_date.isoformat() if f.due_date else "", "days_overdue": f.days_overdue,
                "bucket": "excluded" if f.excluded else f.bucket,
                "bucket_label": "Excluded (" + (c.stage or "") + ")" if f.excluded else BUCKET_LABEL[f.bucket],
                "priority": None if f.excluded else f.priority, "breakdown": f.breakdown,
                "status": f.status, "snooze_until": f.snooze_until.isoformat() if f.snooze_until else "",
                "cold": f.going_cold, "reason": f.reason, "owner": c.owner or "", "notes": c.notes or "",
                "ticket": c.ticket_raw or "", "rows": c.source_rows, "basis": f.basis,
                "issues": [i["msg"] for i in c.issues], "gap": any(i["gap"] for i in c.issues),
                "tool_notes": [{"id": n["id"], "by": n["created_by"], "at": n["created_at"][:16].replace("T", " "),
                                "note": n["note"]} for n in f.tool_notes],
                "draft": {"to": draft.to, "subject": draft.subject, "body": draft.body,
                          "review": drafter.reviewer_note(f)} if draft else None,
            })
        meta = {"as_of": today().isoformat(), "week": this_week_label(today()), "source": r.sheet.path.name,
                "sheet": r.sheet.sheet_name, "warnings": r.warnings, "counts": {
                    "overdue": len(r.overdue), "this_week": len(r.due_this_week), "cold": len(r.going_cold),
                    "gaps": len(r.data_gaps), "snoozed": len(r.snoozed)},
                "owners": sorted({x["owner"] for x in rows if x["owner"]}),
                "stages": [stage_display(cfg, s) for s in cfg["stages"]]}
        return rows, meta, r

    @app.get("/", response_class=HTMLResponse)
    def index():
        try:
            rows, meta, _ = rows_payload()
        except Exception as e:
            return HTMLResponse(f"<pre>Could not read the pipeline: {type(e).__name__}: {e}</pre>", status_code=500)
        return env.get_template("dashboard.html.j2").render(rows=rows, meta=meta)

    @app.get("/api/rows")
    def api_rows():
        rows, meta, _ = rows_payload()
        return {"rows": rows, "meta": meta}

    @app.post("/api/actions")
    def add_action(a: ActionIn):
        if a.kind == "snooze":
            until = a.until or (today() + dt.timedelta(days=a.days or 7))
            if until <= today():
                raise HTTPException(400, "snooze date must be in the future")
            aid = state.add_action(a.contact_id, "snooze", snooze_until=until)
        elif a.kind == "done":
            aid = state.add_action(a.contact_id, "done", basis=a.basis)
        elif a.kind == "note":
            if not (a.note or "").strip():
                raise HTTPException(400, "empty note")
            aid = state.add_action(a.contact_id, "note", note=a.note.strip())
        elif a.kind == "unsnooze":
            for x in state.actions().get(a.contact_id, []):
                if x["kind"] in ("snooze", "done"):
                    state.undo_action(x["id"])
            return {"ok": True}
        else:
            raise HTTPException(400, "unknown action")
        return {"ok": True, "id": aid}

    @app.post("/api/actions/{action_id}/undo")
    def undo(action_id: int):
        state.undo_action(action_id)
        return {"ok": True}

    @app.get("/export.xlsx")
    def export():
        _, _, r = rows_payload()
        drafts = {f.contact.contact_id: drafter.template_draft(f, today()) for f in r.due_now}
        tmp = Path(tempfile.mkdtemp()) / f"followups_{today().isoformat()}.xlsx"
        write_excel(r, cfg, drafts, tmp)
        return FileResponse(tmp, filename=tmp.name,
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return app
