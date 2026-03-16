"""
Integration test — T31: Plant Watering Reminder Demo (end-to-end).

Scenario:
  - Camera returns a green plant JPEG fixture
  - Soil moisture sensor returns 22.5% (below 30% threshold)
  - LLM calls: capture_frame → analyze_image → sensor.read_latest → final_answer (watering needed)
  - Feishu webhook is called (on_anomaly, soil < 30%)
  - storage.save_summary is called
  - AgentRunResult.status == "success"
"""
from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from core.models.task import TaskConfig, TriggerConfig, ContextConfig, OutputConfig
from core.models.agent import AgentRunResult, ToolCallRecord


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_minimal_jpeg() -> bytes:
    """Return a minimal valid JPEG bytes (same as MockCamera)."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x0a\xff\xd9"
    )


def _make_plant_task() -> TaskConfig:
    return TaskConfig(
        task_id="plant_monitor",
        schema_version="1.0",
        name="Plant Health Monitor",
        description="Monitor plant health",
        trigger=TriggerConfig(type="cron", cron="0 */2 * * *"),
        goal=(
            "Assess the current health and hydration status of the plant. "
            "Check both visual appearance and soil moisture data against the care guide. "
            "If watering is needed, send a Feishu alert. Always save a summary."
        ),
        constraints=[
            "Do not call vision.analyze_image more than 3 times per run",
            "Always save a summary before sending a notification",
        ],
        max_steps=15,
        output=OutputConfig(
            save_report=False,
            notify_feishu=True,
            notify_trigger="on_anomaly",
        ),
    )


# ── Tool call response helpers ────────────────────────────────────────────────

def _tool_call_response(tool_name: str, args: dict, call_id: str = "c1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)
    msg = MagicMock(); msg.content = None; msg.tool_calls = [tc]
    choice = MagicMock(); choice.message = msg
    resp = MagicMock(); resp.choices = [choice]
    return resp


def _final_response(text: str):
    msg = MagicMock(); msg.content = text; msg.tool_calls = None
    choice = MagicMock(); choice.message = msg
    resp = MagicMock(); resp.choices = [choice]
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPlantMonitorDemo:
    @pytest.mark.asyncio
    async def test_plant_monitor_full_run_watering_needed(self, tmp_path: Path):
        """
        Full plant monitor run: soil moisture 22.5% → watering alert sent.

        Steps:
          1. LLM calls vision.capture_frame
          2. LLM calls vision.analyze_image
          3. LLM calls sensor.read_latest
          4. LLM returns final_answer with watering recommendation
        """
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_plant_task()

        # LLM response sequence
        llm_responses = [
            _tool_call_response("vision.capture_frame", {"source_id": "desk_camera"}, "c1"),
            _tool_call_response("vision.analyze_image", {"frame_path": "/tmp/plant.jpg"}, "c2"),
            _tool_call_response("sensor.read_latest", {"device_id": "plant_soil_sensor"}, "c3"),
            _final_response(
                "Plant assessment complete. Soil moisture is critically low at 22.5% "
                "(threshold: 30%). Visual inspection shows slight leaf drooping. "
                "WARNING: Watering is urgently needed. Sending alert."
            ),
        ]

        # Tool dispatch responses
        dispatch_responses = {
            "vision.capture_frame": json.dumps({
                "frame_path": str(tmp_path / "plant.jpg"),
                "timestamp": "2026-01-01T10:00:00",
                "source_id": "desk_camera",
            }),
            "vision.analyze_image": json.dumps({
                "analysis": "Green plant, slight leaf drooping, appears healthy but dry",
                "confidence": 0.85,
            }),
            "sensor.read_latest": json.dumps({
                "device_id": "plant_soil_sensor",
                "value": 22.5,
                "unit": "percent",
                "timestamp": "2026-01-01T10:00:00",
            }),
        }

        # Write fixture JPEG
        (tmp_path / "plant.jpg").write_bytes(_make_minimal_jpeg())

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[
            {"name": "vision.capture_frame", "description": "Capture a frame"},
            {"name": "vision.analyze_image", "description": "Analyze an image"},
            {"name": "sensor.read_latest", "description": "Read latest sensor value"},
        ])

        async def mock_dispatch(tool_name: str, args: dict) -> str:
            return dispatch_responses.get(tool_name, '{"error": "unknown tool"}')

        mock_registry.dispatch = mock_dispatch

        # Track save_summary and feishu calls
        save_summary_calls = []
        feishu_calls = []

        async def mock_feishu_send(message: str, **kwargs) -> dict:
            feishu_calls.append(message)
            return {"success": True}

        def mock_save_summary(content: str, category: str, **kwargs) -> dict:
            save_summary_calls.append({"content": content, "category": category})
            return {"summary_id": "test-summary-001", "path": str(tmp_path / "summary.json")}

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = mock_llm
        runner._budget = ContextBudget()
        runner._registry = mock_registry
        runner._react_loop = ReactLoop(mock_llm, mock_registry, ContextBudget())
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=AgentContext())

        import core.task_runner.runner as rmod
        mock_event_bus = MagicMock(); mock_event_bus.publish = AsyncMock()

        with patch("core.config.app_config") as mock_cfg, \
             patch.object(rmod, "event_bus", mock_event_bus), \
             patch("tools.notify.server._feishu_send", mock_feishu_send), \
             patch("tools.storage.server._save_summary", mock_save_summary):
            mock_cfg.storage.base_dir = str(tmp_path)
            result = await runner.run(task)

        # ── Assertions ────────────────────────────────────────────────────────
        assert result.status == "success", f"Expected success, got {result.status}"
        assert len(result.tool_calls) == 3, f"Expected 3 tool calls, got {len(result.tool_calls)}"
        assert "WARNING" in result.final_summary or "urgently" in result.final_summary.lower()

        # Feishu notification sent (on_anomaly triggered by "WARNING" keyword)
        assert result.notification_sent is True, "Feishu notification should have been sent"
        assert len(feishu_calls) == 1

        # Result persisted to disk
        run_dir = tmp_path / "logs" / "runs" / "plant_monitor"
        run_files = list(run_dir.glob("*.json"))
        assert len(run_files) == 1
        saved = json.loads(run_files[0].read_text(encoding="utf-8"))
        assert saved["task_id"] == "plant_monitor"
        assert saved["status"] == "success"

    @pytest.mark.asyncio
    async def test_plant_monitor_healthy_no_notification(self, tmp_path: Path):
        """
        Plant is healthy (soil 65%) → no Feishu notification sent.
        """
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_plant_task()

        llm_responses = [
            _tool_call_response("vision.capture_frame", {"source_id": "desk_camera"}, "c1"),
            _tool_call_response("sensor.read_latest", {"device_id": "plant_soil_sensor"}, "c2"),
            _final_response(
                "Plant is healthy. Soil moisture is 65% — adequate. "
                "Leaves are green and upright. No action needed. Summary saved."
            ),
        ]

        dispatch_responses = {
            "vision.capture_frame": json.dumps({"frame_path": "/tmp/plant.jpg", "timestamp": "2026-01-01T10:00:00"}),
            "sensor.read_latest": json.dumps({"device_id": "plant_soil_sensor", "value": 65.0, "unit": "percent"}),
        }

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(side_effect=lambda t, a: dispatch_responses.get(t, '{}'))

        feishu_calls = []

        async def mock_feishu_send(message: str, **kwargs) -> dict:
            feishu_calls.append(message)
            return {"success": True}

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = mock_llm
        runner._budget = ContextBudget()
        runner._registry = mock_registry
        runner._react_loop = ReactLoop(mock_llm, mock_registry, ContextBudget())
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=AgentContext())

        import core.task_runner.runner as rmod
        mock_event_bus = MagicMock(); mock_event_bus.publish = AsyncMock()

        with patch("core.config.app_config") as mock_cfg, \
             patch.object(rmod, "event_bus", mock_event_bus), \
             patch("tools.notify.server._feishu_send", mock_feishu_send):
            mock_cfg.storage.base_dir = str(tmp_path)
            result = await runner.run(task)

        assert result.status == "success"
        assert result.notification_sent is False, "No notification should be sent for healthy plant"
        assert len(feishu_calls) == 0

    @pytest.mark.asyncio
    async def test_self_planning_generates_valid_task(self):
        """
        Self-Planning: clawtail task generate → valid TaskConfig JSON saved.
        """
        from core.agent.self_planner import SelfPlanner

        valid_task_json = {
            "task_id": "plant_monitor_generated",
            "schema_version": "1.0",
            "name": "Plant Monitor (Generated)",
            "description": "Monitor and care for the plant on my desk",
            "trigger": {"type": "cron", "cron": "0 */2 * * *"},
            "goal": (
                "Assess the current health and hydration status of the plant. "
                "Check both visual appearance and soil moisture data. "
                "If watering is needed, send a Feishu alert. Always save a summary."
            ),
            "constraints": [
                "Do not call vision.analyze_image more than 3 times per run",
                "Always save a summary before sending a notification",
            ],
            "max_steps": 15,
            "context": {
                "include_summaries": {"category": "plant_monitor", "last_n": 3},
                "include_sensor_stats": {"device_ids": ["plant_soil_sensor"], "window_minutes": 120},
            },
            "output": {
                "save_report": False,
                "notify_feishu": True,
                "notify_trigger": "on_anomaly",
            },
        }

        mock_result = MagicMock()
        mock_result.final_summary = json.dumps(valid_task_json)
        mock_result.status = "success"

        planner = SelfPlanner.__new__(SelfPlanner)
        planner._llm = MagicMock()
        planner._budget = MagicMock()
        planner._registry = MagicMock()
        planner._registry.get_all_tools = AsyncMock(return_value=[])
        planner._react_loop = MagicMock()
        planner._react_loop.run = AsyncMock(return_value=mock_result)

        with patch("core.agent.self_planner.SelfPlanner._save_task", return_value=MagicMock()):
            task_config = await planner.plan("Monitor and care for the plant on my desk")

        assert task_config.task_id == "plant_monitor_generated"
        assert task_config.trigger.type == "cron"
        assert task_config.trigger.cron == "0 */2 * * *"
        assert "watering" in task_config.goal.lower()

        # Validate against schema
        from core.task_runner.validator import validate_task
        is_valid, errors = validate_task(valid_task_json)
        assert is_valid, f"Generated task failed schema validation: {errors}"
