"""Shared file utility helpers for writing and backing up config files."""

import logging
import os
import stat
import time
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


def backup_file(path: Path) -> None:
    """Move path to a timestamped .bak file. Raises RuntimeError on failure."""
    backup = path.with_stem(path.stem + f".bak.{int(time.time())}")
    try:
        os.replace(path, backup)
        logger.warning("Backed up %s to %s", path, backup)
    except OSError as e:
        raise RuntimeError(f"Could not back up {path}: {e}") from e


def write_secure(path: Path, content: str) -> None:
    """Write content to path atomically with mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file, returning {} on missing file or parse error."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
