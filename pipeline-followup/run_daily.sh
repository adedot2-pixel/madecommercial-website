#!/usr/bin/env bash
# Daily run (macOS/Linux/cron). Example crontab line, weekdays 07:30:
#   30 7 * * 1-5 /path/to/pipeline-followup/run_daily.sh >> /path/to/pipeline-followup/data/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
PYTHONPATH="$PWD/src" exec "$PY" -m pipeline_followup run --config config/config.yaml "$@"
