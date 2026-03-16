"""
Local storage directory initializer for ClawWithTail.
Creates the ~/.clawtail/ directory tree on first run.
Corresponds to plan-01.md S0-5 + spec.md §2.2 Storage.
"""
from __future__ import annotations

from pathlib import Path

_VERSION = "0.1.0"

_REQUIRED_SUBDIRS = [
    "data/frames",
    "data/sensor_logs",
    "data/reports",
    "summaries",
    "tasks",
    "logs/runs",
    "models",
    "cache/care_guides",
]


def init_storage(base_dir: str | Path = "~/.clawtail") -> Path:
    """
    Create the ClawWithTail data directory tree under base_dir.
    Safe to call multiple times — existing directories are not modified.

    Returns the resolved absolute Path of base_dir.
    """
    root = Path(base_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    for subdir in _REQUIRED_SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)

    # Write version marker
    version_file = root / ".clawtail_version"
    if not version_file.exists():
        version_file.write_text(_VERSION, encoding="utf-8")

    return root
