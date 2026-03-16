"""
Integration tests for storage MCP Tool Package (T24 — Sprint 2 gate).
Tests the full save → list → read roundtrip.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.storage.server import _save_summary, _list_summaries, _read_summary, _save_report, _read_report
from tools.shared.errors import PathTraversalError


class TestStorageRoundtrip:
    def test_save_list_read_roundtrip(self, tmp_path: Path):
        """Full roundtrip: save → list → read returns consistent data."""
        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            # Save 3 summaries with different categories
            r1 = _save_summary("Plant is healthy, soil moisture at 65%.", "plant_monitor", ["daily"])
            r2 = _save_summary("Temperature stable at 23°C.", "chemistry_monitor", ["lab"])
            r3 = _save_summary("Plant needs water, soil moisture at 20%.", "plant_monitor", ["alert"])

            # List all plant_monitor summaries
            plant_summaries = _list_summaries(category="plant_monitor")
            assert len(plant_summaries) == 2

            # List with last_n=1
            latest = _list_summaries(category="plant_monitor", last_n=1)
            assert len(latest) == 1

            # Read back the first summary
            read_result = _read_summary(r1["summary_id"])
            assert read_result["content"] == "Plant is healthy, soil moisture at 65%."
            assert read_result["metadata"]["category"] == "plant_monitor"
            assert "daily" in read_result["metadata"]["tags"]

    def test_list_sorted_by_recency(self, tmp_path: Path):
        """list_summaries returns results sorted by created_at descending."""
        import time
        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            r1 = _save_summary("First", "test")
            time.sleep(0.01)  # Ensure different timestamps
            r2 = _save_summary("Second", "test")
            time.sleep(0.01)
            r3 = _save_summary("Third", "test")

            results = _list_summaries(category="test")

        # Most recent first
        assert results[0]["summary_id"] == r3["summary_id"]
        assert results[-1]["summary_id"] == r1["summary_id"]


class TestReportRoundtrip:
    def test_save_and_read_report(self, tmp_path: Path):
        """save_report → read_report returns identical content."""
        content = "# Plant Health Report\n\nThe plant is healthy.\n\n## Recommendations\n- Continue watering weekly."
        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            save_result = _save_report(content, "Plant Health Report", "plant_monitor")
            read_result = _read_report(save_result["report_path"])

        assert read_result["content"] == content

    def test_report_filename_format(self, tmp_path: Path):
        """Report filename follows the {date}_{task_id}_{slug}.md format."""
        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            result = _save_report("Content", "My Test Report", "plant_monitor")

        filename = Path(result["report_path"]).name
        assert filename.endswith(".md")
        assert "plant_monitor" in filename
        assert "my_test_report" in filename.lower()

    def test_path_traversal_blocked(self, tmp_path: Path):
        """Path traversal attacks are blocked."""
        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            with pytest.raises(PathTraversalError):
                _read_report("../../../etc/passwd")

            with pytest.raises(PathTraversalError):
                _read_report("/etc/shadow")
