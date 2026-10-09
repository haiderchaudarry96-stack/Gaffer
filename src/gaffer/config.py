"""Load `config.yaml` (and `.env`) into a plain dict.

Every threshold, model id, path and region lives in `config.yaml`; nothing is hard-coded.
Environment variables from `.env` override a few AWS settings (`AWS_PROFILE`, `AWS_REGION`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


class ConfigError(RuntimeError):
    """Raised when the config file is missing or malformed."""


def _load_dotenv() -> None:
    """Load `.env` from the repo root if python-dotenv is available and the file exists."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dependency is pinned
        return
    load_dotenv(env_path, override=False)


@lru_cache(maxsize=4)
def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return the parsed configuration.

    Args:
        path: Config file to read. Defaults to `$GAFFER_CONFIG` or `<repo>/config.yaml`.

    Raises:
        ConfigError: if the file does not exist or is not a YAML mapping.
    """
    _load_dotenv()
    cfg_path = Path(path or os.environ.get("GAFFER_CONFIG") or DEFAULT_CONFIG_PATH)
    if not cfg_path.is_absolute():
        cfg_path = REPO_ROOT / cfg_path
    if not cfg_path.exists():
        raise ConfigError(f"Config file not found: {cfg_path}")
    with cfg_path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ConfigError(f"Config file {cfg_path} must contain a YAML mapping.")

    aws = cfg.setdefault("aws", {})
    if os.environ.get("AWS_REGION"):
        aws["region"] = os.environ["AWS_REGION"]
    if os.environ.get("AWS_PROFILE"):
        aws["profile"] = os.environ["AWS_PROFILE"]
    return cfg


def repo_path(relative: str | os.PathLike[str]) -> Path:
    """Resolve a config path (relative to the repo root) to an absolute path."""
    p = Path(relative)
    return p if p.is_absolute() else REPO_ROOT / p
