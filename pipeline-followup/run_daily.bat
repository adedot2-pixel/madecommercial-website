@echo off
REM Daily run: reads the pipeline sheet, writes digest/drafts/Excel to the output folder.
REM Schedule this file with Windows Task Scheduler (see README).
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m pipeline_followup run --config config\config.yaml %*
