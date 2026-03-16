"""
Integration test — T34: System startup smoke test (full pipeline).

Tests:
  1. Full startup sequence: init_storage → get_env_profile → PollManager.start
     → start_webhook_server → task_scheduler.load_tasks → task_scheduler.start
  2. All example tasks registered in scheduler
  3. system.start event triggers drinking_watcher
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSystemStartup:
    @pytest.mark.asyncio
    async def test_full_startup_sequence(self, tmp_path: Path):
        """
        Full startup sequence completes without error.
        All example tasks are loaded into the scheduler.
        """
        from core.storage_init import init_storage
        from core.scheduler.event_bus import EventBus

        # 1. init_storage
        root = init_storage(str(tmp_path))
        assert (tmp_path / "tasks").exists()
        assert (tmp_path / "logs").exists()
        assert (tmp_path / "summaries").exists()

        # 2. get_env_profile (mock cv2 to avoid camera enumeration)
        with patch("cv2.VideoCapture") as mock_cap:
            mock_cap.return_value.isOpened.return_value = False
            from env.state import reset_env_profile, get_env_profile
            reset_env_profile()
            profile = get_env_profile()
            assert profile.os in ("windows", "linux", "macos", "unknown")
            assert profile.yolo_variant in ("yolov8n", "yolov8s", "yolov8m", "yolov8l")

        # 3. PollManager.start / stop
        from core.bus import poll_manager
        poll_manager.start()
        poll_manager.stop()

        # 4. Scheduler loads example tasks
        from core.scheduler.scheduler import TaskScheduler
        from core.task_runner.runner import TaskRunner

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=MagicMock(status="success"))
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)
        scheduler._scheduler = MagicMock()

        # Copy example tasks to tmp tasks dir
        import shutil
        examples_dir = Path(__file__).parent.parent.parent / "tasks" / "examples"
        tasks_dir = tmp_path / "tasks"
        for json_file in examples_dir.glob("*.json"):
            shutil.copy(json_file, tasks_dir / json_file.name)

        with patch("core.config.app_config") as mock_cfg:
            mock_cfg.storage.base_dir = str(tmp_path)
            n_tasks = scheduler.load_tasks()

        # Should have loaded at least 3 example tasks
        assert n_tasks >= 3, f"Expected >= 3 tasks, got {n_tasks}"
        assert "plant_monitor" in scheduler._task_registry
        assert "chemistry_monitor" in scheduler._task_registry

    @pytest.mark.asyncio
    async def test_system_start_event_triggers_watcher(self, tmp_path: Path):
        """
        Publishing system.start event triggers the drinking_watcher task.
        """
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus
        from core.models.task import TaskConfig, TriggerConfig, OutputConfig

        run_count = [0]

        async def mock_run(task):
            run_count[0] += 1
            return MagicMock(status="success")

        mock_runner = MagicMock()
        mock_runner.run = mock_run
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)
        scheduler._scheduler = MagicMock()

        # Register drinking_watcher task
        watcher_task = TaskConfig(
            task_id="drinking_watcher",
            schema_version="1.0",
            name="Drinking Activity Watcher",
            description="Start background watcher",
            trigger=TriggerConfig(type="on_event", event="system.start"),
            goal="Start a background watcher to monitor drinking activity",
            output=OutputConfig(),
        )
        scheduler.register_task(watcher_task)

        # Publish system.start
        await event_bus.publish("system.start", {"source": "test"})
        await asyncio.sleep(0.2)

        assert run_count[0] == 1, "drinking_watcher should have been triggered by system.start"

    @pytest.mark.asyncio
    async def test_webhook_server_accepts_sensor_push(self, tmp_path: Path):
        """
        Webhook server accepts POST /webhook/{device_id} and returns {"status": "ok"}.
        """
        from httpx import AsyncClient, ASGITransport
        from core.bus.webhook_server import create_webhook_app
        from core.bus import bus

        # Mock devices_config
        mock_devices = {
            "lab_temp_sensor": MagicMock(
                device_id="lab_temp_sensor",
                type="sensor",
                protocol="wifi_push",
            )
        }

        with patch("core.bus.webhook_server.devices_config", mock_devices):
            app = create_webhook_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/webhook/lab_temp_sensor",
                    json={"value": 25.3, "unit": "celsius"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestFullReactLoop:
    @pytest.mark.asyncio
    async def test_plant_monitor_full_react_loop(self):
        """
        Full ReAct loop for plant_monitor task (4 steps):
          1. capture_frame
          2. analyze_image
          3. sensor.read_latest
          4. final_answer

        Verifies:
          - tool_calls length == 3
          - final_summary is non-empty
          - context budget not exceeded (< 8000 tokens)
        """
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext
        from core.models.task import TaskConfig, TriggerConfig, OutputConfig

        task = TaskConfig(
            task_id="plant_monitor",
            schema_version="1.0",
            name="Plant Health Monitor",
            description="Monitor plant health",
            trigger=TriggerConfig(type="cron", cron="0 */2 * * *"),
            goal=(
                "Assess the current health and hydration status of the plant. "
                "Check both visual appearance and soil moisture data. "
                "If watering is needed, send a Feishu alert. Always save a summary."
            ),
            constraints=["Do not call vision.analyze_image more than 3 times per run"],
            max_steps=20,
            output=OutputConfig(),
        )

        def _tc(name, args, cid):
            tc = MagicMock(); tc.id = cid; tc.function.name = name
            tc.function.arguments = json.dumps(args)
            msg = MagicMock(); msg.content = None; msg.tool_calls = [tc]
            choice = MagicMock(); choice.message = msg
            resp = MagicMock(); resp.choices = [choice]
            return resp

        def _fa(text):
            msg = MagicMock(); msg.content = text; msg.tool_calls = None
            choice = MagicMock(); choice.message = msg
            resp = MagicMock(); resp.choices = [choice]
            return resp

        llm_responses = [
            _tc("vision.capture_frame", {"source_id": "desk_camera"}, "c1"),
            _tc("vision.analyze_image", {"frame_path": "/tmp/plant.jpg"}, "c2"),
            _tc("sensor.read_latest", {"device_id": "plant_soil_sensor"}, "c3"),
            _fa(
                "Plant assessment complete. Soil moisture is 22.5% — below threshold. "
                "Leaf color is green but slightly drooping. "
                "WARNING: Watering recommended. Summary saved."
            ),
        ]

        dispatch_responses = {
            "vision.capture_frame": json.dumps({"frame_path": "/tmp/plant.jpg", "timestamp": "2026-01-01T10:00:00"}),
            "vision.analyze_image": json.dumps({"analysis": "Green plant, slight drooping", "confidence": 0.85}),
            "sensor.read_latest": json.dumps({"device_id": "plant_soil_sensor", "value": 22.5, "unit": "percent"}),
        }

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[
            {"name": "vision.capture_frame", "description": "Capture frame"},
            {"name": "vision.analyze_image", "description": "Analyze image"},
            {"name": "sensor.read_latest", "description": "Read sensor"},
        ])
        mock_registry.dispatch = AsyncMock(
            side_effect=lambda t, a: dispatch_responses.get(t, '{}')
        )

        budget = ContextBudget()
        loop = ReactLoop(mock_llm, mock_registry, budget)
        result = await loop.run(task, AgentContext())

        # Assertions
        assert result.status == "success", f"Expected success, got {result.status}: {result.error}"
        assert len(result.tool_calls) == 3, f"Expected 3 tool calls, got {len(result.tool_calls)}"
        assert result.final_summary, "final_summary should not be empty"
        assert "WARNING" in result.final_summary or "watering" in result.final_summary.lower()

        # Context budget check: estimate total tokens used
        total_tokens = budget.estimate_tokens(result.final_summary)
        for tc in result.tool_calls:
            total_tokens += budget.estimate_tokens(str(tc.output))
        assert total_tokens < 8000, f"Context budget exceeded: {total_tokens} tokens"


class TestCLIValidation:
    def test_cli_validate_valid_task(self, tmp_path: Path):
        """
        clawtail task validate <valid_json> → outputs '✅ Valid'.
        """
        from typer.testing import CliRunner
        from cli.main import app

        valid_task = {
            "task_id": "plant_monitor",
            "schema_version": "1.0",
            "name": "Plant Health Monitor",
            "description": "Monitor plant health and soil moisture",
            "trigger": {"type": "cron", "cron": "0 */2 * * *"},
            "goal": (
                "Assess the current health and hydration status of the plant. "
                "Check both visual appearance and soil moisture data. "
                "If watering is needed, send a Feishu alert. Always save a summary."
            ),
            "constraints": ["Do not call vision.analyze_image more than 3 times per run"],
            "max_steps": 15,
            "output": {"save_report": False, "notify_feishu": True, "notify_trigger": "on_anomaly"},
        }

        task_file = tmp_path / "plant_monitor.json"
        task_file.write_text(json.dumps(valid_task, indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(app, ["task", "validate", str(task_file)])

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.output}"
        assert "Valid" in result.output

    def test_cli_validate_invalid_task(self, tmp_path: Path):
        """
        clawtail task validate <invalid_json> → outputs error message, exit code 1.
        """
        from typer.testing import CliRunner
        from cli.main import app

        # Missing required 'goal' field
        invalid_task = {
            "task_id": "broken_task",
            "schema_version": "1.0",
            "name": "Broken Task",
            "description": "This task is missing required fields",
            "trigger": {"type": "manual"},
            # 'goal' is missing
        }

        task_file = tmp_path / "broken_task.json"
        task_file.write_text(json.dumps(invalid_task, indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(app, ["task", "validate", str(task_file)])

        assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
        assert "Invalid" in result.output or "goal" in result.output.lower()

    def test_cli_task_list_no_tasks(self, tmp_path: Path):
        """
        clawtail task list with empty tasks dir → shows 'No tasks found' message.
        """
        from typer.testing import CliRunner
        from cli.main import app

        with patch("core.config.app_config") as mock_cfg:
            mock_cfg.storage.base_dir = str(tmp_path)
            runner = CliRunner()
            result = runner.invoke(app, ["task", "list"])

        assert result.exit_code == 0
        assert "No tasks" in result.output or "tasks directory" in result.output.lower()
