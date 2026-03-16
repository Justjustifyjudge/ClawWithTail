"""
Unit tests for TaskRunner (T27 — Sprint 3 gate).
Tests output policy: save_report, notify on_anomaly.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.agent import AgentRunResult, ToolCallRecord
from core.models.task import TaskConfig, TriggerConfig, OutputConfig, ContextConfig


def _make_result(status="success", final_summary="Plant is healthy.", has_anomaly=False):
    if has_anomaly:
        final_summary = "WARNING: soil moisture critically low, plant needs water urgently."
    return AgentRunResult(
        task_id="plant_monitor",
        run_id="test-run-id",
        started_at=datetime.now(tz=timezone.utc),
        finished_at=datetime.now(tz=timezone.utc),
        status=status,
        final_summary=final_summary,
    )


def _make_task(save_report=False, notify_feishu=False, notify_trigger="on_complete"):
    return TaskConfig(
        task_id="plant_monitor",
        schema_version="1.0",
        name="Plant Monitor",
        description="Monitor plant health",
        trigger=TriggerConfig(type="manual"),
        goal="Check plant health",
        output=OutputConfig(
            save_report=save_report,
            notify_feishu=notify_feishu,
            notify_trigger=notify_trigger,
        ),
    )


class TestTaskRunnerOutputPolicy:
    @pytest.mark.asyncio
    async def test_save_report_called_when_enabled(self, tmp_path: Path):
        """TaskRunner calls save_report when output.save_report=True."""
        from core.task_runner.runner import TaskRunner

        task = _make_task(save_report=True)
        mock_result = _make_result()

        mock_react = MagicMock()
        mock_react.run = AsyncMock(return_value=mock_result)

        mock_save_report = MagicMock(return_value={"report_path": str(tmp_path / "report.md")})

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = MagicMock()
        runner._budget = MagicMock()
        runner._registry = MagicMock()
        runner._registry.get_all_tools = AsyncMock(return_value=[])
        runner._react_loop = mock_react
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=MagicMock())

        with patch("core.task_runner.runner.TaskRunState") as mock_state_cls, \
             patch("core.task_runner.runner.event_bus") as mock_bus, \
             patch("tools.storage.server._save_report", mock_save_report):
            mock_state_cls.return_value.save_result = MagicMock()
            mock_bus.publish = AsyncMock()

            result = await runner.run(task)

        mock_save_report.assert_called_once()
        assert result.report_path is not None

    @pytest.mark.asyncio
    async def test_save_report_not_called_when_disabled(self):
        """TaskRunner does NOT call save_report when output.save_report=False."""
        from core.task_runner.runner import TaskRunner

        task = _make_task(save_report=False)
        mock_result = _make_result()

        mock_react = MagicMock()
        mock_react.run = AsyncMock(return_value=mock_result)
        mock_save_report = MagicMock()

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = MagicMock()
        runner._budget = MagicMock()
        runner._registry = MagicMock()
        runner._registry.get_all_tools = AsyncMock(return_value=[])
        runner._react_loop = mock_react
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=MagicMock())

        with patch("core.task_runner.runner.TaskRunState") as mock_state_cls, \
             patch("core.task_runner.runner.event_bus") as mock_bus, \
             patch("tools.storage.server._save_report", mock_save_report):
            mock_state_cls.return_value.save_result = MagicMock()
            mock_bus.publish = AsyncMock()
            await runner.run(task)

        mock_save_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_on_anomaly_fires_when_anomaly(self):
        """TaskRunner sends notification when notify_trigger=on_anomaly and anomaly detected."""
        from core.task_runner.runner import TaskRunner

        task = _make_task(notify_feishu=True, notify_trigger="on_anomaly")
        mock_result = _make_result(has_anomaly=True)

        mock_react = MagicMock()
        mock_react.run = AsyncMock(return_value=mock_result)
        mock_feishu = AsyncMock(return_value={"success": True})

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = MagicMock()
        runner._budget = MagicMock()
        runner._registry = MagicMock()
        runner._registry.get_all_tools = AsyncMock(return_value=[])
        runner._react_loop = mock_react
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=MagicMock())

        with patch("core.task_runner.runner.TaskRunState") as mock_state_cls, \
             patch("core.task_runner.runner.event_bus") as mock_bus, \
             patch("tools.notify.server._feishu_send", mock_feishu):
            mock_state_cls.return_value.save_result = MagicMock()
            mock_bus.publish = AsyncMock()
            result = await runner.run(task)

        mock_feishu.assert_called_once()
        assert result.notification_sent is True

    @pytest.mark.asyncio
    async def test_notify_on_anomaly_silent_when_no_anomaly(self):
        """TaskRunner does NOT send notification when notify_trigger=on_anomaly but no anomaly."""
        from core.task_runner.runner import TaskRunner

        task = _make_task(notify_feishu=True, notify_trigger="on_anomaly")
        mock_result = _make_result(has_anomaly=False)

        mock_react = MagicMock()
        mock_react.run = AsyncMock(return_value=mock_result)
        mock_feishu = AsyncMock()

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = MagicMock()
        runner._budget = MagicMock()
        runner._registry = MagicMock()
        runner._registry.get_all_tools = AsyncMock(return_value=[])
        runner._react_loop = mock_react
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=MagicMock())

        with patch("core.task_runner.runner.TaskRunState") as mock_state_cls, \
             patch("core.task_runner.runner.event_bus") as mock_bus, \
             patch("tools.notify.server._feishu_send", mock_feishu):
            mock_state_cls.return_value.save_result = MagicMock()
            mock_bus.publish = AsyncMock()
            result = await runner.run(task)

        mock_feishu.assert_not_called()
        assert result.notification_sent is False

    @pytest.mark.asyncio
    async def test_result_persisted_to_disk(self, tmp_path: Path):
        """TaskRunner persists AgentRunResult to ~/.clawtail/logs/runs/{task_id}/{run_id}.json."""
        from core.task_runner.runner import TaskRunner
        from core.task_runner.state import TaskRunState

        task = _make_task()
        mock_result = _make_result()

        mock_react = MagicMock()
        mock_react.run = AsyncMock(return_value=mock_result)

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = MagicMock()
        runner._budget = MagicMock()
        runner._registry = MagicMock()
        runner._registry.get_all_tools = AsyncMock(return_value=[])
        runner._react_loop = mock_react
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=MagicMock())

        with patch("core.config.app_config") as mock_cfg, \
             patch("core.task_runner.runner.event_bus") as mock_bus:
            mock_cfg.storage.base_dir = str(tmp_path)
            mock_bus.publish = AsyncMock()
            result = await runner.run(task)

        # Verify file was created
        run_dir = tmp_path / "logs" / "runs" / "plant_monitor"
        run_files = list(run_dir.glob("*.json"))
        assert len(run_files) == 1
        saved = json.loads(run_files[0].read_text(encoding="utf-8"))
        assert saved["task_id"] == "plant_monitor"
        assert saved["status"] == "success"


class TestTaskRunnerShouldNotify:
    def test_always_trigger(self):
        from core.task_runner.runner import TaskRunner
        task = _make_task(notify_trigger="always")
        result = _make_result(status="failed")
        assert TaskRunner._should_notify(task, result) is True

    def test_on_complete_success(self):
        from core.task_runner.runner import TaskRunner
        task = _make_task(notify_trigger="on_complete")
        result = _make_result(status="success")
        assert TaskRunner._should_notify(task, result) is True

    def test_on_complete_failed(self):
        from core.task_runner.runner import TaskRunner
        task = _make_task(notify_trigger="on_complete")
        result = _make_result(status="failed")
        assert TaskRunner._should_notify(task, result) is False

    def test_on_anomaly_with_keyword(self):
        from core.task_runner.runner import TaskRunner
        task = _make_task(notify_trigger="on_anomaly")
        result = _make_result(final_summary="WARNING: temperature critical")
        assert TaskRunner._should_notify(task, result) is True

    def test_on_anomaly_without_keyword(self):
        from core.task_runner.runner import TaskRunner
        task = _make_task(notify_trigger="on_anomaly")
        result = _make_result(final_summary="Everything is normal.")
        assert TaskRunner._should_notify(task, result) is False
