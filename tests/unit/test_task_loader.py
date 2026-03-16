"""
Unit tests for Task JSON validator and loader (T09 — Sprint 0 gate).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.task_runner.validator import validate_task
from core.task_runner.loader import load_task, TaskLoadError


VALID_TASK = {
    "task_id": "test_task",
    "schema_version": "1.0",
    "name": "Test Task",
    "description": "A test task for unit testing",
    "trigger": {"type": "manual"},
    "goal": "This is a test goal with enough characters to pass validation.",
}


class TestValidateTask:
    def test_valid_task_passes(self):
        is_valid, errors = validate_task(VALID_TASK)
        assert is_valid is True
        assert errors == []

    def test_missing_required_field(self):
        task = {**VALID_TASK}
        del task["goal"]
        is_valid, errors = validate_task(task)
        assert is_valid is False
        assert any("goal" in e for e in errors)

    def test_cron_trigger_requires_cron_field(self):
        task = {**VALID_TASK, "trigger": {"type": "cron"}}
        is_valid, errors = validate_task(task)
        assert is_valid is False
        assert any("cron" in e for e in errors)

    def test_cron_trigger_with_cron_field_passes(self):
        task = {**VALID_TASK, "trigger": {"type": "cron", "cron": "0 */2 * * *"}}
        is_valid, errors = validate_task(task)
        assert is_valid is True

    def test_on_event_trigger_requires_event_field(self):
        task = {**VALID_TASK, "trigger": {"type": "on_event"}}
        is_valid, errors = validate_task(task)
        assert is_valid is False
        assert any("event" in e for e in errors)

    def test_invalid_schema_version(self):
        task = {**VALID_TASK, "schema_version": "2.0"}
        is_valid, errors = validate_task(task)
        assert is_valid is False

    def test_max_steps_out_of_range(self):
        task = {**VALID_TASK, "max_steps": 100}
        is_valid, errors = validate_task(task)
        assert is_valid is False


class TestLoadTask:
    def test_loads_plant_monitor_example(self):
        """The plant_monitor.json example file loads successfully."""
        path = Path(__file__).parent.parent.parent / "tasks" / "examples" / "plant_monitor.json"
        task = load_task(path)
        assert task.task_id == "plant_monitor"
        assert task.trigger.type == "cron"
        assert task.trigger.cron == "0 */2 * * *"

    def test_loads_chemistry_monitor_example(self):
        path = Path(__file__).parent.parent.parent / "tasks" / "examples" / "chemistry_monitor.json"
        task = load_task(path)
        assert task.task_id == "chemistry_monitor"
        assert task.output.save_report is True

    def test_loads_drinking_watcher_example(self):
        path = Path(__file__).parent.parent.parent / "tasks" / "examples" / "drinking_watcher.json"
        task = load_task(path)
        assert task.task_id == "drinking_summarizer"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(TaskLoadError, match="not found"):
            load_task(tmp_path / "nonexistent.json")

    def test_invalid_json_raises(self, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ not valid json }", encoding="utf-8")
        with pytest.raises(TaskLoadError, match="Invalid JSON"):
            load_task(bad_file)

    def test_schema_violation_raises(self, tmp_path: Path):
        bad_task = {"task_id": "x", "schema_version": "1.0"}  # missing required fields
        bad_file = tmp_path / "bad_task.json"
        bad_file.write_text(json.dumps(bad_task), encoding="utf-8")
        with pytest.raises(TaskLoadError, match="validation failed"):
            load_task(bad_file)
