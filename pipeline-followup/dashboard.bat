@echo off
REM Opens the local dashboard in the browser (http://127.0.0.1:8765). Close this window to stop it.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m pipeline_followup serve --config config\config.yaml --open %*
