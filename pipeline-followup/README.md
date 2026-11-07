# Pipeline Follow-up Tool (prototype)

Reads the EA's investor pipeline spreadsheet and tells the Head of EMEA **who to follow up with, and when**.
It produces a daily digest, copy-ready draft emails, an Excel export and a local dashboard.

**It never sends anything, and it never writes to the spreadsheet.**

```
Pipeline.xlsx (read-only) ─▶ map columns ─▶ clean & de-duplicate ─▶ follow-up rules ─▶ priority
                                                                             │
       config/config.yaml (column + stage mapping, rules)                    ▼
       data/state.db (snooze / done / notes, snapshots)  ◀──▶  digest.html · digest.eml · drafts.txt
                                                               followups.xlsx · dashboard (127.0.0.1)
```

## Contents
1. [Quick start (demo)](#1-quick-start-demo)
2. [Setup on a Windows laptop](#2-setup-on-a-windows-laptop)
3. [Pointing it at the real spreadsheet (column mapping)](#3-pointing-it-at-the-real-spreadsheet)
4. [Daily run and scheduling](#4-daily-run-and-scheduling)
5. [What it produces](#5-what-it-produces)
6. [How follow-ups and priority are worked out](#6-how-follow-ups-and-priority-are-worked-out)
7. [The dashboard](#7-the-dashboard)
8. [Optional AI drafting](#8-optional-ai-drafting-off-by-default)
9. [Data-handling summary for IT / Compliance](#9-data-handling-summary-for-it--compliance)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Quick start (demo)

```bash
pip install -r requirements.txt
```

```bash
python -m pipeline_followup demo --open
```

(From the project folder. If the package isn't installed, set `PYTHONPATH=src` first, or run
`pip install -e .`.)

`demo` does three things:
- Generates a messy, fictional 50-row pipeline in `demo/Pipeline.xlsx`, plus the same sheet as it
  looked a week earlier.
- Runs against last week's sheet and then this week's, so change tracking has something to report.
- Writes the outputs to `demo/output/<date>/`.

To see the dashboard on the demo data:

```bash
python -m pipeline_followup serve --config demo/demo_config.yaml --open
```

A pre-generated copy of the demo outputs is in [`sample_output/`](sample_output/). It includes the dummy
spreadsheet, the digest, drafts and Excel export. All names, firms and email domains are fictional, and
the emails use the reserved `.example` domain.

The dummy sheet is deliberately messy, to show what the tool handles:
- A title row above the header, blank rows, and section headings ("NORDICS") merged across the row.
- Firm names merged vertically across several contacts.
- Eight different date formats: real dates, `03/11/2026`, `3-Nov-26`, `Nov 03, 2026`, `6 Nov`, an
  Excel serial number, `TBC`, `last week`.
- Stages typed differently: `Mtg held`, `Met`, `DDQ`, `In DD`, `Due Dilligence` (typo), `soft circle`,
  `Verbal`, `Funded`, `Hot`.
- Mixed currencies and formats: `£40m`, `€10-15m`, `NOK 300m`, `c.20m`, `250k`.
- Duplicate contacts (`James O'Neill` / `james o'neill … Ltd`; `Charlotte Ashby` / `Ashby, Charlotte`),
  an invalid email, a row with no name, and a blank stage.

## 2. Setup on a Windows laptop

You need Python 3.10 or later. If IT restricts installs, the packages needed are in `requirements.txt`.
They are pandas, openpyxl, PyYAML, Jinja2, FastAPI, uvicorn and pydantic. All are mainstream, open
source and on PyPI.

```bat
cd C:\Tools\pipeline-followup
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy config\config.example.yaml config\config.yaml
```

Then edit `config\config.yaml`. At minimum, set:
- `source.path`: where the pipeline spreadsheet lives (a local path, a mapped drive such as
  `S:\IR\Pipeline.xlsx`, or a UNC path such as `\\server\share\IR\Pipeline.xlsx`).
- `state.db`: where the shared tool state lives (see below).
- `drafts.sender_name`, `sender_title`, `fund_name`.

**Shared state (EA + Head of EMEA).** Point `state.db` at the **shared drive**, e.g.
`S:\IR\PipelineTool\state.db`, so both people see the same snoozes, done marks and notes. Each action
records the Windows user name of whoever made it.
- The database uses SQLite's rollback journal rather than WAL, because WAL doesn't work on network
  shares. It also keeps transactions short and waits up to 20 seconds for a lock.
- This is safe for two or three people clicking occasionally. It is not designed for heavy concurrent
  use.
- Outputs (`output.dir`) and the log can stay local or go on the share as well.

## 3. Pointing it at the real spreadsheet

The tool never assumes column names. It maps the sheet's headers to its own fields through the config.

**Step 1: inspect the sheet.**

```bat
.venv\Scripts\python -m pipeline_followup inspect --file "S:\IR\Pipeline.xlsx"
```

This prints:
- Which sheet and header row it found, how many rows it read, merged ranges, and skipped blank and
  heading rows.
- Every column, with how full it is and sample values.
- A **suggested mapping** with a confidence score for each field. Anything below 0.8 is marked
  "please check".
- **Missing fields:**
  - Required: name, firm. The tool cannot run without them.
  - Key: stage, last contact date, who acted last, next action date, email. Follow-up dates are less
    reliable without them.
  - Optional: everything else.
- Stage values it could only match by similarity, and stage values it couldn't recognise at all.

It also writes `config/config.suggested.yaml`. Review its `columns:` and `stages:` sections, then copy
them into `config/config.yaml`.

**Step 2: the mapping format.**

```yaml
columns:                    # tool field: the sheet's header (case and extra spaces ignored)
  name: "Contact"
  firm: ["Company", "Firm"] # a list = whichever exists (survives the EA renaming a column)
  stage: "Status"
  last_contact_date: "Last touch"
  last_actor: "Last move by"
  ticket_size: null         # not in this sheet
```

Fields are `name, firm, email, investor_type, stage, last_contact_date, last_contact_type, last_actor,
next_action, next_action_date, owner, ticket_size, notes`. Only name and firm are required.

**Stages.** The seven standard stages are fixed: Intro, Meeting held, Materials sent, Due diligence,
Soft commit, Invested, Dormant.
- Under `stages:`, list the words people actually type for each one.
- Matching ignores case and punctuation.
- Close misspellings are accepted but flagged.
- Anything unrecognised is listed under **Data gaps** until it's added to the config.
- To show the team's own wording on screen, use `display_stage_names`, e.g. `{"Due diligence": "DD"}`.

**Contact identity.**
- If the sheet has a unique ID column (a CRM ID, for example), map it as `record_id`. Contacts then keep
  their snooze, done and notes history even if a name or firm is retyped.
- Without an ID, a contact is identified by name + firm. If either changes, the next run matches the
  contact by email or by name, reports it as **Renamed** in the change list, and carries its history
  over.

**Who acted last.** If the sheet records *whose turn it is* ("ball in our court") rather than *who
acted last*, set `values.last_actor_column_means: whose_turn` and the tool flips it. `inspect` spots headers like
"Ball in court" or "Waiting on" and sets this in the suggested config for you to confirm.

**Currencies.**
- Each ticket keeps the currency it was entered in. `$ € £` and codes like `CHF` or `NOK` are
  recognised.
- A bare number uses `tickets.default_currency` and `default_unit` (e.g. `25` = 25m).
- For scoring and totals, tickets are converted to `base_currency` at the fixed rates in
  `tickets.fx_to_base`. Record the date they were set in `tickets.fx_as_of`; the digest warns when they
  are more than 90 days old.
- The pipeline table also shows the totals per currency as entered.

## 4. Daily run and scheduling

Run it once with:

```bat
run_daily.bat
```

which is the same as:

```bat
.venv\Scripts\python -m pipeline_followup run --config config\config.yaml
```

Useful options: `--open` (opens the digest), `--as-of 2026-11-09` (pretends it's another day, for
testing), and `--file other.xlsx`.

**Windows Task Scheduler** (weekdays at 07:30):

```bat
schtasks /Create /TN "Pipeline follow-ups" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:30 /TR "\"C:\Tools\pipeline-followup\run_daily.bat\""
```

**cron** (macOS/Linux): see the comment at the top of `run_daily.sh`.

Each run records a line in `data/runs.log` and a row in the `runs` table of `state.db`. These hold the
time, who ran it, the file's SHA-256 fingerprint, counts and the status, but no names, emails or notes.

## 5. What it produces

Each run writes to `output/<YYYY-MM-DD>/`:

| File | What it is |
|---|---|
| `digest.html` | The daily page. Sections: Overdue · Due this week (Mon–Fri) · Going cold · Changes since last run · Data gaps · Pipeline count and value by stage · Coming up. |
| `digest.eml` | The same digest as an **unsent** email (`X-Unsent: 1`). Double-click it and Outlook opens it as a draft; review it, then send it yourself. |
| `drafts.txt` | A copy-ready draft email for every overdue or due-this-week contact. Each one comes with a reviewer note: why it's due, the sheet notes, tool notes and a compliance reminder. |
| `followups.xlsx` | The prioritised follow-up list (with draft subject and body), plus Data gaps, Changes, and Pipeline-by-stage sheets. |

**Change tracking.** Each run is compared with the previous successful run. It reports:
- new contacts, renamed contacts, and contacts no longer in the sheet;
- stage moves (forward or back);
- contacts that went quiet (crossed the going-cold threshold);
- new activity logged, next-action date changes and ticket changes.

## 6. How follow-ups and priority are worked out

All numbers below can be changed under `rules:` and `priority:` in the config.

| Situation in the sheet | Due date | Rule |
|---|---|---|
| Next action date filled in | that date (an explicit date from the EA always wins) | `explicit` |
| Last contact was a **meeting**, nothing logged since | meeting + **2 working days** | `after_meeting` |
| **They** acted last | last contact + **3 working days** | `they_acted` |
| **We** acted last | last contact + **10 days** (nudge) | `we_acted` |
| Who acted last not recorded | last contact + 10 days | `unknown_actor` |
| No contact for **30+ days** | flagged as **going cold** (its own digest section) | |
| Stage is **Invested** or **Dormant** | excluded (`rules.excluded_stages`) | |

If no explicit date is set and more than one rule applies, the earliest date is used.
- Working days skip weekends and England & Wales bank holidays (built in for 2025–2027). Add other
  closures in `rules.extra_holidays`.
- **Due this week** means Monday to Friday of the current week. At the weekend it means the coming
  week.

**Priority (0–100)** = urgency (45) + stage (35) + ticket size (20):
- **Urgency:** overdue items score 50–100% of 45, rising with days overdue (capped at 14 days). Items
  due today, this week or later score less. Going cold adds a bonus.
- **Stage:** weight per stage, so later stages score higher (Soft commit 1.0 … Intro 0.2).
- **Ticket:** log-scaled against the largest ticket in the pipeline. If the ticket is unknown, the
  median is used and marked as estimated.

The dashboard shows the breakdown for every row, so any ranking can be explained.

**Messy-data handling:**
- Title rows and blank rows are skipped, and the header row is detected automatically.
- Merged cells are filled in.
- Section-heading rows are skipped.
- Dates are read in many formats, day-first by default. Dates without a year get the current year,
  and this is flagged.
- Duplicates are matched on the same name + firm or the same email. Case, titles, "Surname, First"
  and suffixes like Ltd/AG are ignored. The tool keeps the most recently contacted row, fills its
  blanks from the other rows, and lists the duplicate under Data gaps.

## 7. The dashboard

Start it from a command prompt:

```bat
dashboard.bat
```

or:

```bat
.venv\Scripts\python -m pipeline_followup serve --config config\config.yaml --open
```

It opens a plain table at `http://127.0.0.1:8765`.
- Columns: contact, firm, stage, last contact, days since, next action, due date, priority and status.
- Click a column heading to sort. Filter with the search box or by due state, stage and owner.
- Click a name to see why it's due, the priority breakdown, sheet notes, data problems and the Excel
  row number.
- **Snooze** (2 days to 1 month, or a chosen date) hides the item until that date.
- **Done** hides it until the sheet changes for that contact (new contact date, stage, next action…),
  so a contact can't be hidden forever by mistake.
- **Note** adds a dated note with the user's name.
- **Draft** shows the draft with copy buttons. **Export to Excel** downloads the current list.

Snooze, done and notes are stored only in `state.db`. The spreadsheet is never touched. The dashboard
re-reads the spreadsheet on every page load, so it is always current.

## 8. Optional AI drafting (off by default)

Template drafts are the default. They are short, professional, British English, and contain no
performance figures or fund terms. The templates are plain text files in
`src/pipeline_followup/templates/drafts/` and can be edited by anyone. Free-text sheet notes are **never**
pasted into email bodies; they appear in the reviewer note only.

**Recommended path: a local model first.** A model running on the laptop means no data leaves the
machine, so no new data-sharing approval is needed.

1. Install [Ollama](https://ollama.com) on the laptop. This needs IT approval, but it's a local app.
2. Download a model:
   ```bat
   ollama pull llama3.1:8b
   ```
3. Trial it on **fictional** data. `ai-check` uses the dummy pipeline unless `--real` is given, and
   prints template and AI drafts side by side:
   ```bat
   .venv\Scripts\python -m pipeline_followup ai-check
   ```
4. If the drafts are better, set `drafts.ai.enabled: true` (provider `ollama`). Any failure falls back
   to the template draft.

**Anthropic API (Claude): only after sign-off.**
- The firm's **Claude Enterprise** licence covers the claude.ai app. It does **not** cover calls from this
  tool, which need an API key from the Anthropic Console under the firm's API data terms.
- The tool **refuses** to use `provider: anthropic` until `drafts.ai.external_provider_approval` records
  who approved it and when, e.g. `"Compliance (J. Smith) + IT, 2026-12-01, ref CR-123"`. Each run logs
  the provider and the approval text.
- Setup:
  1. `pip install anthropic`
  2. Set the `ANTHROPIC_API_KEY` environment variable.
  3. Set `provider: anthropic` and `model: claude-opus-5-5`.
  4. Try it first with `ai-check --provider anthropic`.
- The call enables server-side refusal fallback (`fallbacks: "default"`). If the model declines a
  request, another Claude model is tried within the same call.

**What a model receives:**
- first name, firm, investor type and stage;
- when and how the last contact happened, and who acted last;
- why the follow-up is due, and the next action.

Email addresses are **never** sent. Free-text notes are sent only if `send_notes: true`. Ollama's address
must be this machine; the config rejects a remote one. The dashboard always shows template drafts, so
loading a page never calls a model.

## 9. Data-handling summary for IT / Compliance

| Topic | Position |
|---|---|
| Purpose | Internal reminder and drafting aid for investor-relations follow-ups. A person reviews every output. |
| Source data | The existing pipeline spreadsheet. **Read-only:** the file's bytes are read into memory and parsed there, and the file is never opened for writing. A test checks that its hash and modified time are unchanged after a run. |
| Sending | **The tool cannot send email.** There is no SMTP, Graph or Outlook-send code. The `.eml` is marked unsent and opens as a draft for a person to send. |
| Network | **None by default.** The tool loads no web fonts, CDNs or analytics, and sends no telemetry. The dashboard binds to `127.0.0.1` only (the config refuses any other host), rejects requests with a foreign Host or Origin header, and has the API docs endpoints switched off. The only optional outbound call is AI drafting (section 8). It is off by default, the local option
stays on this machine, and the external (Anthropic) option is blocked until an approval is recorded in
the config. |
| Data stored by the tool | `state.db` (SQLite) holds: run log; per-run **minimal snapshots** (name, firm, stage, last-contact date, next-action date, ticket, and a one-way SHA-256 fingerprint of the email used only to recognise renamed contacts; **no notes, no plain email addresses**) for change tracking, purged after `snapshot_retention_days` (default 120); snooze/done/notes typed in the dashboard, with the Windows user name. Outputs in `output/<date>/` contain contact details and drafts. Store them where the spreadsheet is allowed to live, and delete old folders as per retention policy. |
| Logs | `runs.log` and the `runs` table hold timestamps, user, file fingerprint (SHA-256), counts and errors. No personal data. |
| Access control | Inherits the file-system permissions of wherever the spreadsheet, `state.db` and `output/` are stored. There is no separate user database and no passwords. |
| Dependencies | Python plus pandas, openpyxl, PyYAML, Jinja2, FastAPI, uvicorn, pydantic, all from PyPI. `anthropic` only if that provider is enabled. |
| Removal | Delete the folder, `state.db` and the output folders. Nothing is installed system-wide, apart from a Task Scheduler entry if one was created. |

## 10. Troubleshooting

- **"Required column for 'name' not found".** The header names changed. Run `inspect` and update
  `columns:`. A list of alternative names avoids this next time.
- **A stage shows up under Data gaps.** Add the typed word under the right stage in `stages:`.
- **Dates read the wrong way round (US format).** Set `values.day_first: false`, and put `%m/%d/%Y`
  first in `date_formats`.
- **"database is locked" on the shared drive.** Someone else's click was mid-save. Retry. If it
  persists, check the share's permissions and that the file isn't open in another tool.
- **The file is open in Excel.** That's fine: the tool only reads it. It sees the last *saved* version.

## Project layout

```
config/config.example.yaml       documented config (copy to config.yaml)
src/pipeline_followup/
  ingest.py      read-only workbook reader (header detection, merged cells, blank/section rows)
  mapping.py     header -> field suggestions for `inspect`
  normalise.py   dates, stages, types, tickets/currencies, duplicates
  rules.py       follow-up rules, UK working-day calendar, priority score
  engine.py      sheet -> contacts -> follow-ups (+ snooze/done/notes)
  changes.py     compare with the previous snapshot
  drafts.py      template drafts; optional AI (ollama / anthropic)
  outputs.py     digest.html, digest.eml, drafts.txt, followups.xlsx
  state.py       SQLite (runs, snapshots, changes, actions)
  web/app.py     local dashboard (FastAPI)
  templates/     digest, dashboard and draft templates
  dummy.py       messy fake pipeline generator
tests/           pytest suite (python -m pytest)
sample_output/   pre-generated demo outputs on fictional data
QUESTIONS.md     what to confirm against the real spreadsheet
```
