"""
Unit tests for storage MCP Tool Package (T24 — Sprint 2 gate).
Tests save/read/list summaries and save/read reports with path traversal protection.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.shared.errors import ToolError, PathTraversalError


class TestSaveSummary:
    def test_save_creates_json_file(self, tmp_path: Path):
        """save_summary creates a JSON file in the summaries directory."""
        from tools.storage.server import _save_summary

        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            result = _save_summary("Plant looks healthy.", "plant_monitor", ["daily"])

        assert "summary_id" in result
        assert "path" in result
        saved_file = Path(result["path"])
        assert saved_file.exists()
        record = json.loads(saved_file.read_text(encoding="utf-8"))
        assert record["content"] == "Plant looks healthy."
        assert record["category"] == "plant_monitor"
        assert "daily" in record["tags"]

    def test_save_without_tags(self, tmp_path: Path):
        """save_summary works without tags."""
        from tools.storage.server import _save_summary

        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            result = _save_summary("Test content", "test_category")

        assert result["summary_id"] is not None
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert record["tags"] == []


class TestReadSummary:
    def test_read_returns_content_and_metadata(self, tmp_path: Path):
        """read_summary returns content and metadata for a saved summary."""
        from tools.storage.server import _save_summary, _read_summary

        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            save_result = _save_summary("Test content", "test", ["tag1"])
            read_result = _read_summary(save_result["summary_id"])

        assert read_result["content"] == "Test content"
        assert read_result["metadata"]["category"] == "test"
        assert "tag1" in read_result["metadata"]["tags"]

    def test_read_nonexistent_raises_tool_error(self, tmp_path: Path):
        """read_summary raises ToolError for non-existent summary ID."""
        from tools.storage.server import _read_summary

        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            with pytest.raises(ToolError, match="not found"):
                _read_summary("nonexistent-id")


class TestListSummaries:
    def test_list_all(self, tmp_path: Path):
        """list_summaries returns all summaries when no filters applied."""
        from tools.storage.server import _save_summary, _list_summaries

        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            _save_summary("Content A", "plant_monitor")
            _save_summary("Content B", "chemistry_monitor")
            _save_summary("Content C", "plant_monitor")
            results = _list_summaries()

        assert len(results) == 3

    def test_list_filter_by_category(self, tmp_path: Path):
        """list_summaries filters by category correctly."""
        from tools.storage.server import _save_summary, _list_summaries

        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            _save_summary("Plant A", "plant_monitor")
            _save_summary("Chem B", "chemistry_monitor")
            _save_summary("Plant C", "plant_monitor")
            results = _list_summaries(category="plant_monitor")

        assert len(results) == 2
        assert all(r["category"] == "plant_monitor" for r in results)

    def test_list_last_n(self, tmp_path: Path):
        """list_summaries respects last_n limit."""
        from tools.storage.server import _save_summary, _list_summaries

        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            for i in range(5):
                _save_summary(f"Content {i}", "plant_monitor")
            results = _list_summaries(category="plant_monitor", last_n=2)

        assert len(results) == 2

    def test_list_snippet_max_200_chars(self, tmp_path: Path):
        """list_summaries snippet is at most 200 characters."""
        from tools.storage.server import _save_summary, _list_summaries

        long_content = "x" * 500
        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            _save_summary(long_content, "test")
            results = _list_summaries()

        assert len(results[0]["snippet"]) <= 200


class TestSaveReport:
    def test_save_report_creates_markdown_file(self, tmp_path: Path):
        """save_report creates a .md file in the reports directory."""
        from tools.storage.server import _save_report

        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            result = _save_report("# Report\nContent here.", "Plant Health Report", "plant_monitor")

        assert "report_path" in result
        report_file = Path(result["report_path"])
        assert report_file.exists()
        assert report_file.suffix == ".md"
        assert report_file.read_text(encoding="utf-8") == "# Report\nContent here."

    def test_save_report_filename_contains_task_id(self, tmp_path: Path):
        """save_report filename includes the task_id."""
        from tools.storage.server import _save_report

        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            result = _save_report("Content", "My Report", "plant_monitor")

        assert "plant_monitor" in result["report_path"]


class TestReadReport:
    def test_read_report_returns_content(self, tmp_path: Path):
        """read_report returns the content of a saved report."""
        from tools.storage.server import _save_report, _read_report

        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            save_result = _save_report("# Test Report", "Test", "test_task")
            read_result = _read_report(save_result["report_path"])

        assert read_result["content"] == "# Test Report"

    def test_read_report_path_traversal_rejected(self, tmp_path: Path):
        """read_report rejects path traversal attempts."""
        from tools.storage.server import _read_report

        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            with pytest.raises(PathTraversalError, match="Access denied"):
                _read_report("/etc/passwd")

    def test_read_report_traversal_with_dotdot(self, tmp_path: Path):
        """read_report rejects ../../../etc/passwd style attacks."""
        from tools.storage.server import _read_report

        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            with pytest.raises(PathTraversalError, match="Access denied"):
                _read_report(str(tmp_path / ".." / ".." / "etc" / "passwd"))
