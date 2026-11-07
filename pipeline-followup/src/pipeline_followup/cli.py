"""Command line: inspect | run | serve | demo."""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import webbrowser
from pathlib import Path

import yaml

from . import __version__
from .config import FIELDS, ConfigError, load_config, load_defaults, resolve_path

DEFAULT_CONFIG = Path("config") / "config.yaml"


def _config_path(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    return DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else None


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


# ---------------- inspect ----------------
def cmd_inspect(args) -> int:
    from .ingest import read_sheet
    from .mapping import last_actor_hint, missing_fields, suggest_mapping, suggest_stage_aliases

    cfg_path = _config_path(args.config)
    cfg = load_config(cfg_path)
    if args.file:
        cfg["source"]["path"] = str(Path(args.file).resolve())
    if args.sheet:
        cfg["source"]["sheet"] = args.sheet
    path = resolve_path(cfg, cfg["source"]["path"])
    sheet = read_sheet(path, cfg)
    print(f"File:        {path}")
    print(f"Sheets:      {', '.join(sheet.sheet_names)}  (using '{sheet.sheet_name}')")
    print(f"Header row:  {sheet.header_row}   data rows: {len(sheet.rows)}   merged ranges: {sheet.merged_ranges}"
          f"   skipped: {', '.join(f'{v} {k}' for k, v in sheet.skipped.items() if v)}")
    print("\nColumns found:")
    for i, h in enumerate(sheet.headers):
        if not h:
            continue
        samples = [str(r[i]) for _, r in sheet.rows if r[i] is not None][:3]
        filled = sum(1 for _, r in sheet.rows if r[i] is not None)
        print(f"  {i + 1:>2}. {h[:28]:<28} {filled:>3}/{len(sheet.rows)} filled   e.g. {' | '.join(s[:22] for s in samples)}")

    sug = suggest_mapping(sheet)
    print("\nSuggested mapping (tool field <- sheet header):")
    for f in FIELDS:
        if f in sug:
            s = sug[f]
            flag = "" if s["confidence"] >= 0.8 else "   <- please check"
            print(f"  {f:<18} <- {s['header']:<28} confidence {s['confidence']:.2f} ({s['why']}){flag}")
        else:
            print(f"  {f:<18} <- (not found)")
    miss = missing_fields(sug)
    if miss["required"]:
        print(f"\n!! REQUIRED fields missing: {', '.join(miss['required'])} - the tool cannot run without them.")
    if miss["key"]:
        print(f"\n!  Key fields missing: {', '.join(miss['key'])} - follow-up dates will be less reliable.")
    if miss["optional"]:
        print(f"   Optional fields not found: {', '.join(miss['optional'])}")

    hint = last_actor_hint(sug)
    if hint:
        print(f"\n!  {hint}")
    if "record_id" not in sug:
        print("\n   No unique ID column found: contacts are identified by name + firm (renames are detected by\n"
              "   email or name and their history carried over, but an ID column is more reliable).")
    additions, unmatched = {}, []
    if "stage" in sug:
        idx = sheet.headers.index(sug["stage"]["header"])
        additions, unmatched = suggest_stage_aliases([r[idx] for _, r in sheet.rows], cfg)
        if additions:
            print("\nStage values matched by similarity (added to the suggested config - please confirm):")
            for st, vals in additions.items():
                print(f"  {st:<15} <- {', '.join(vals)}")
        if unmatched:
            print(f"\n!  Stage values not recognised (add them under 'stages' in the config): {', '.join(unmatched)}")

    out_cfg = load_defaults()
    out_cfg["source"]["path"] = str(path)
    out_cfg["source"]["sheet"] = sheet.sheet_name
    out_cfg["source"]["header_row"] = sheet.header_row
    out_cfg["columns"] = {f: sug[f]["header"] for f in FIELDS if f in sug}
    if hint:
        out_cfg["values"]["last_actor_column_means"] = "whose_turn"
    for st, vals in additions.items():
        out_cfg["stages"][st] = sorted(set(out_cfg["stages"].get(st, []) + vals))
    out = Path(args.out) if args.out else (cfg_path.parent if cfg_path else Path("config")) / "config.suggested.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (f"# Suggested by `inspect` on {dt.date.today()} for {path.name}.\n"
              f"# Check the 'columns' and 'stages' sections, then save as config.yaml.\n"
              f"# Unrecognised stage values: {', '.join(unmatched) or 'none'}\n"
              f"# See config.example.yaml for an explanation of every setting.\n")
    out.write_text(header + yaml.safe_dump(out_cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"\nWrote {out}")
    return 1 if miss["required"] else 0


# ---------------- run ----------------
def cmd_run(args) -> int:
    from .runner import run

    cfg = load_config(_config_path(args.config))
    if args.file:
        cfg["source"]["path"] = str(Path(args.file).resolve())
    r, out_dir = run(cfg, args.as_of)
    print(f"\nOverdue: {len(r.overdue)}   Due this week: {len(r.due_this_week)}   Going cold: {len(r.going_cold)}   "
          f"Data gaps: {len(r.data_gaps)}   Changes: {len(r.changes)}")
    print(f"Outputs: {out_dir}")
    for name in ("digest.html", "digest.eml", "drafts.txt", "followups.xlsx"):
        if (out_dir / name).exists():
            print(f"  - {out_dir / name}")
    if args.open:
        webbrowser.open((out_dir / "digest.html").as_uri())
    return 0


# ---------------- serve ----------------
def cmd_serve(args) -> int:
    import uvicorn

    from .web.app import create_app

    cfg = load_config(_config_path(args.config))
    app = create_app(cfg, args.as_of)
    host, port = cfg["dashboard"]["host"], int(args.port or cfg["dashboard"]["port"])
    url = f"http://{host}:{port}/"
    print(f"Dashboard: {url}  (local only; Ctrl+C to stop)")
    if args.open:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


# ---------------- ai-check ----------------
def cmd_ai_check(args) -> int:
    """Try the configured AI provider and compare its drafts with the template drafts.
    Uses the FICTIONAL demo data unless --real is given, so a trial never exposes real contacts."""
    import json
    import tempfile
    import time
    import urllib.request

    from .config import external_approval
    from .drafts import Drafter
    from .dummy import generate
    from .engine import evaluate

    cfg = load_config(_config_path(args.config))
    ai = cfg["drafts"]["ai"]
    if args.provider:
        ai["provider"] = args.provider
    if args.model:
        ai["model"] = args.model
    elif args.provider == "anthropic" and "claude" not in str(ai.get("model")):
        ai["model"] = "claude-opus-5-5"
    provider = ai["provider"]
    print(f"Provider: {provider}   model: {ai.get('model')}   enabled in config: {bool(ai.get('enabled'))}")

    if provider == "ollama":
        print(f"Data stays on this machine ({ai['ollama_url']}).")
        try:
            with urllib.request.urlopen(ai["ollama_url"].rstrip("/") + "/api/tags", timeout=5) as r:
                models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        except Exception as e:
            print(f"\nCannot reach Ollama at {ai['ollama_url']}: {e}\n"
                  "Install Ollama (https://ollama.com), start it, then run:\n"
                  f"  ollama pull {ai.get('model') or 'llama3.1:8b'}")
            return 2
        print(f"Local models installed: {', '.join(models) or '(none)'}")
        wanted = ai.get("model") or "llama3.1:8b"
        if not any(m == wanted or m.split(":")[0] == wanted for m in models):
            print(f"\nModel '{wanted}' is not installed. Run:\n  ollama pull {wanted}")
            return 2
    elif provider == "anthropic":
        approval = external_approval(cfg)
        if not approval:
            print("\nRefused: the 'anthropic' provider sends contact data to the Anthropic API.\n"
                  "Fill in drafts.ai.external_provider_approval in the config once IT and Compliance have\n"
                  "signed off (the Claude Enterprise licence covers the claude.ai app, not API use).")
            return 2
        print(f"EXTERNAL provider - data leaves this machine. Approval on record: {approval}")
    else:
        print("Unknown provider")
        return 2

    if args.real:
        print("\nUsing the REAL spreadsheet from the config.")
        r = evaluate(cfg, dt.date.today())
        as_of = dt.date.today()
    else:
        tmp = Path(tempfile.mkdtemp())
        as_of = dt.date.today()
        cur, _ = generate(tmp, as_of)
        cfg["source"]["path"] = str(cur)
        cfg["source"]["sheet"] = None
        cfg["columns"] = load_defaults()["columns"]
        print("\nUsing FICTIONAL demo data (pass --real to try the configured spreadsheet).")
        r = evaluate(cfg, as_of)
    ai["enabled"] = True
    drafter = Drafter(cfg)
    picks = r.due_now[: args.n]
    ok = 0
    for f in picks:
        base = drafter.template_draft(f, as_of)
        t0 = time.time()
        d = drafter.draft(f, as_of)
        secs = time.time() - t0
        ok += d.source.startswith("ai:")
        print("\n" + "=" * 78)
        print(f"{f.contact.display_name} ({f.contact.firm}) - {f.reason}")
        print("-" * 34 + " TEMPLATE " + "-" * 34)
        print(base.body)
        print("-" * 30 + f" {d.source.upper()} ({secs:.1f}s) " + "-" * 30)
        print(d.body if d.source.startswith("ai:") else "(AI draft failed - see warning above; template would be used)")
    print(f"\n{ok}/{len(picks)} AI drafts produced. Nothing was sent. "
          f"To use AI in the daily run, set drafts.ai.enabled: true in the config.")
    return 0 if ok == len(picks) else 1


# ---------------- demo ----------------
DEMO_CONFIG = """# Demo config - points at the generated dummy spreadsheet. Paths are relative to this file.
source:
  path: "Pipeline.xlsx"
state:
  db: "state.db"
  log: "runs.log"
output:
  dir: "output"
"""


def cmd_demo(args) -> int:
    from .dummy import generate
    from .runner import run

    as_of = args.as_of or dt.date.today()
    demo_dir = Path(args.dir).resolve()
    if demo_dir.exists() and (demo_dir / "demo_config.yaml").exists():
        shutil.rmtree(demo_dir)  # only ever removes a folder this command created
    demo_dir.mkdir(parents=True, exist_ok=True)
    cur, prev = generate(demo_dir, as_of)
    cfg_file = demo_dir / "demo_config.yaml"
    cfg_file.write_text(DEMO_CONFIG, encoding="utf-8")
    print(f"Generated dummy spreadsheets:\n  {cur}\n  {prev}")

    print("\n[1/2] Run against last week's sheet (to create a baseline snapshot)")
    cfg = load_config(cfg_file)
    cfg["source"]["path"] = str(prev)
    run(cfg, as_of - dt.timedelta(days=7))
    print("\n[2/2] Run against the current sheet")
    cfg = load_config(cfg_file)
    r, out_dir = run(cfg, as_of)
    print(f"\nOverdue: {len(r.overdue)}   Due this week: {len(r.due_this_week)}   Going cold: {len(r.going_cold)}   "
          f"Data gaps: {len(r.data_gaps)}   Changes since last week: {len(r.changes)}")
    print(f"\nOutputs in {out_dir}")
    print(f"Open the dashboard with:\n  python -m pipeline_followup serve --config \"{cfg_file}\" --open")
    if args.open:
        webbrowser.open((out_dir / "digest.html").as_uri())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline_followup",
                                description="Investor pipeline follow-up tool (read-only, drafts never sent).")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspect", help="Inspect a spreadsheet and suggest a column mapping")
    s.add_argument("--file", help="xlsx to inspect (default: source.path from config)")
    s.add_argument("--sheet")
    s.add_argument("--config")
    s.add_argument("--out", help="where to write the suggested config")
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("run", help="Daily run: digest, drafts, Excel export, change report")
    s.add_argument("--config")
    s.add_argument("--file", help="override source.path")
    s.add_argument("--as-of", type=_date, help="pretend today is YYYY-MM-DD")
    s.add_argument("--open", action="store_true", help="open the digest in the browser")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("serve", help="Local dashboard (sort/filter, snooze, done, notes)")
    s.add_argument("--config")
    s.add_argument("--port", type=int)
    s.add_argument("--as-of", type=_date)
    s.add_argument("--open", action="store_true")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("ai-check", help="Try the AI drafting provider on fictional data, next to template drafts")
    s.add_argument("--config")
    s.add_argument("--provider", choices=["ollama", "anthropic"])
    s.add_argument("--model")
    s.add_argument("-n", type=int, default=3, help="number of sample drafts (default 3)")
    s.add_argument("--real", action="store_true", help="use the configured (real) spreadsheet instead")
    s.set_defaults(func=cmd_ai_check)

    s = sub.add_parser("demo", help="Generate the dummy spreadsheet and run against it")
    s.add_argument("--dir", default="demo")
    s.add_argument("--as-of", type=_date)
    s.add_argument("--open", action="store_true")
    s.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
