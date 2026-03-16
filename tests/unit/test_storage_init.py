"""
Unit tests for local storage initializer (T09 — Sprint 0 gate).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.storage_init import init_storage, _REQUIRED_SUBDIRS


class TestInitStorage:
    def test_creates_all_subdirs(self, tmp_path: Path):
        """init_storage creates all required subdirectories."""
        root = init_storage(tmp_path / "clawtail_test")
        for subdir in _REQUIRED_SUBDIRS:
            assert (root / subdir).is_dir(), f"Missing directory: {subdir}"

    def test_creates_version_file(self, tmp_path: Path):
        """init_storage creates .clawtail_version file."""
        root = init_storage(tmp_path / "clawtail_test")
        version_file = root / ".clawtail_version"
        assert version_file.exists()
        assert version_file.read_text().strip() == "0.1.0"

    def test_idempotent(self, tmp_path: Path):
        """Calling init_storage twice does not raise an error."""
        base = tmp_path / "clawtail_test"
        init_storage(base)
        init_storage(base)  # should not raise

    def test_returns_resolved_path(self, tmp_path: Path):
        """init_storage returns the resolved absolute Path."""
        base = tmp_path / "clawtail_test"
        result = init_storage(base)
        assert result.is_absolute()
        assert result == base.resolve()

    def test_frames_dir_exists(self, tmp_path: Path):
        """data/frames directory is created (used by camera adapter)."""
        root = init_storage(tmp_path / "clawtail_test")
        assert (root / "data" / "frames").is_dir()
