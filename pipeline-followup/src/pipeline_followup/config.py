"""Load and validate the YAML config (user file deep-merged over the packaged defaults)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = PACKAGE_DIR / "default_config.yaml"

STANDARD_STAGES = [
    "Intro",
    "Meeting held",
    "Materials sent",
    "Due diligence",
    "Soft commit",
    "Invested",
    "Dormant",
]
FIELDS = [
    "name", "firm", "email", "investor_type", "stage", "last_contact_date",
    "last_contact_type", "last_actor", "next_action", "next_action_date",
    "owner", "ticket_size", "notes",
]
REQUIRED_FIELDS = ["name", "firm"]
# Fields without which the follow-up rules cannot work well
KEY_FIELDS = ["stage", "last_contact_date", "last_actor", "next_action_date", "email"]


class ConfigError(Exception):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("columns", "stages"):
            out[k] = _deep_merge(out[k], v)
        else:
            # columns/stages are replaced wholesale so a user can remove entries
            out[k] = copy.deepcopy(v)
    return out


def load_defaults() -> dict:
    with open(DEFAULT_CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(path: str | Path | None) -> dict:
    """Return the merged config. `_base_dir` is where relative paths are resolved from."""
    cfg = load_defaults()
    base_dir = Path.cwd() / "config"
    if path:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}")
        with open(p, encoding="utf-8") as f:
            try:
                user = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ConfigError(f"Config file is not valid YAML: {e}") from e
        if not isinstance(user, dict):
            raise ConfigError("Config file must be a YAML mapping")
        cfg = _deep_merge(cfg, user)
        base_dir = p.resolve().parent
    cfg["_base_dir"] = str(base_dir)
    validate(cfg)
    return cfg


def resolve_path(cfg: dict, value: str | Path) -> Path:
    p = Path(str(value)).expanduser()
    if not p.is_absolute():
        p = Path(cfg["_base_dir"]) / p
    return p.resolve()


def validate(cfg: dict) -> None:
    problems = []
    cols = cfg.get("columns") or {}
    for k in cols:
        if k not in FIELDS:
            problems.append(f"columns: unknown field '{k}' (allowed: {', '.join(FIELDS)})")
    for k in cfg.get("stages") or {}:
        if k not in STANDARD_STAGES:
            problems.append(f"stages: '{k}' is not a standard stage ({', '.join(STANDARD_STAGES)})")
    for s in cfg["rules"].get("excluded_stages", []):
        if s not in STANDARD_STAGES:
            problems.append(f"rules.excluded_stages: '{s}' is not a standard stage")
    w = cfg["priority"]["weights"]
    if any(not isinstance(v, (int, float)) or v < 0 for v in w.values()):
        problems.append("priority.weights must be non-negative numbers")
    if cfg["values"].get("last_actor_column_means", "acted_last") not in ("acted_last", "whose_turn"):
        problems.append("values.last_actor_column_means must be 'acted_last' or 'whose_turn'")
    ai = cfg["drafts"]["ai"]
    if ai.get("enabled") and ai.get("provider") not in ("ollama", "anthropic"):
        problems.append("drafts.ai.provider must be 'ollama' or 'anthropic'")
    host = str(cfg["dashboard"].get("host", "127.0.0.1"))
    if host not in ("127.0.0.1", "localhost", "::1"):
        problems.append("dashboard.host must be 127.0.0.1/localhost (the dashboard is local-only by design)")
    if problems:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(problems))


def column_candidates(cfg: dict, field: str) -> list[str]:
    v = (cfg.get("columns") or {}).get(field)
    if v is None:
        return []
    return [v] if isinstance(v, str) else [str(x) for x in v]


def stage_display(cfg: dict, stage: str | None) -> str:
    if not stage:
        return "(none)"
    return (cfg.get("display_stage_names") or {}).get(stage, stage)
