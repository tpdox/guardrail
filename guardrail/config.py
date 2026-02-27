"""Configuration loading from guardrail.yml and environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SnowflakeConfig:
    account: str = ""
    user: str = ""
    warehouse: str = ""
    role: str = ""
    private_key_file: str = ""


@dataclass
class Thresholds:
    null_rate_fail: float = 0.05
    null_rate_warn: float = 0.001
    fk_match_rate_fail: float = 0.95
    fk_match_rate_warn: float = 0.99


@dataclass
class GuardrailConfig:
    dbt_project_dir: str = ""
    base_branch: str = "main"
    snowflake: SnowflakeConfig = field(default_factory=SnowflakeConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)
    join_keys: dict[str, dict[str, list[str]]] = field(default_factory=dict)


def _resolve_env(val: str) -> str:
    """Expand ~ and $ENV_VAR references in string values."""
    if isinstance(val, str):
        val = os.path.expanduser(val)
        val = os.path.expandvars(val)
    return val


def find_config_path() -> Path | None:
    """Search for config in standard locations."""
    env = os.environ.get("GUARDRAIL_CONFIG")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p
    xdg = Path.home() / ".config" / "guardrail" / "guardrail.yml"
    if xdg.exists():
        return xdg
    cwd = Path.cwd() / "guardrail.yml"
    if cwd.exists():
        return cwd
    return None


def load_config(config_path: str | Path | None = None) -> GuardrailConfig:
    """Load guardrail configuration from YAML file.

    Falls back to sensible defaults if no config file is provided.
    """
    cfg = GuardrailConfig()

    if config_path is None:
        return cfg

    config_path = Path(config_path)
    if not config_path.exists():
        return cfg

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    cfg.dbt_project_dir = _resolve_env(raw.get("dbt_project_dir", ""))
    cfg.base_branch = raw.get("base_branch", "main")

    sf = raw.get("snowflake", {})
    cfg.snowflake = SnowflakeConfig(
        account=_resolve_env(sf.get("account", "")),
        user=_resolve_env(sf.get("user", "")),
        warehouse=_resolve_env(sf.get("warehouse", "")),
        role=_resolve_env(sf.get("role", "")),
        private_key_file=_resolve_env(sf.get("private_key_file", "")),
    )

    th = raw.get("thresholds", {})
    cfg.thresholds = Thresholds(
        null_rate_fail=th.get("null_rate_fail", 0.05),
        null_rate_warn=th.get("null_rate_warn", 0.001),
        fk_match_rate_fail=th.get("fk_match_rate_fail", 0.95),
        fk_match_rate_warn=th.get("fk_match_rate_warn", 0.99),
    )

    cfg.join_keys = raw.get("join_keys", {})

    return cfg
