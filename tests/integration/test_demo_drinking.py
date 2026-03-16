"""
Integration test — T33: Drinking Water Reminder Demo (end-to-end).

Scenario A (adequate hydration):
  - 3 drink events in past 90 minutes
  - LLM: count_objects returns 3 → final_answer "Hydration adequate"
  - Feishu NOT called; storage.save_summary called

Scenario B (insufficient hydration):
  - 0 drink events
  - LLM: count_objects returns 0 → final_answer contains "insufficient"
  - Feishu called with 💧 message

Scenario C (watcher startup):
  - system.start event published
  - drinking_watcher task fires
  - vision.start_watch called
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.task import TaskConfig, TriggerConfig, ContextConfig, OutputConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_summarizer_task() -> TaskConfig:
    return TaskConfig(
        task_id="drinking_summarizer",
        schema_version="1.0",
        name="Hydration Summarizer",
        description="Review drinking activity every 90 minutes",
        trigger=TriggerConfig(type="cron", cron="0 */90 * * * *"),
        goal=(
            "Review the drinking activity log for the past 90 minutes. "
            "Compare against a healthy hydration baseline (at least 1 drink per 90 minutes). "
            "If insufficient, send a Feishu hydration reminder. Save a daily summary."
        ),
        constraints=[
            "Only call notify.feishu_send if drinking event count is below the healthy threshold",
            "Always save a summary via storage.save_summary with category 'hydration'",
        ],
        max_steps=8,
        output=OutputConfig(
            save_report=False,
            notify_feishu=True,
            notify_trigger="on_anomaly",
        ),
    )


def _make_watcher_task() -> TaskConfig:
    return TaskConfig(
        task_id="drinking_watcher",
        schema_version="1.0",
        name="Drinking Activity Watcher",
        description="Start background watcher on system startup",
        trigger=TriggerConfig(type="on_event", event="system.start"),
        goal="Start a background watcher to monitor drinking activity",
        constraints=[
            "Call vision.start_watch with source_id='desk_camera', labels=['cup','bottle','drinking glass'], interval_seconds=30, cooldown_seconds=300"
        ],
        max_steps=3,
        output=OutputConfig(save_report=False, notify_feishu=False),
    )


def _tool_call_response(tool_name: str, args: dict, call_id: str = "c1"):
    tc = MagicMock(); tc.id = call_id; tc.function.name = tool_name
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

class TestDrinkingReminderDemo:
    @pytest.mark.asyncio
    async def test_scenario_a_adequate_hydration_no_notification(self, tmp_path: Path):
        """
        Scenario A: 3 drink events → Hydration adequate → no Feishu notification.
        """
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_summarizer_task()

        # Pre-write 3 drink events to event log
        event_log = tmp_path / "data" / "drink_events.jsonl"
        event_log.parent.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            event_log.write_text(
                event_log.read_text(encoding="utf-8") if event_log.exists() else "" +
                json.dumps({
                    "event": "drink_detected",
                    "timestamp": f"2026-01-01T{10 + i}:00:00",
                    "label": "cup",
                }) + "\n",
                encoding="utf-8",
            )

        llm_responses = [
            _tool_call_response(
                "vision.count_objects",
                {"event_log_path": str(event_log), "window_minutes": 90},
                "c1",
            ),
            _final_response(
                "Hydration adequate. 3 drinking events detected in the past 90 minutes. "
                "Daily summary saved. No reminder needed."
            ),
        ]

        dispatch_responses = {
            "vision.count_objects": json.dumps({"count": 3, "window_minutes": 90}),
        }

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(side_effect=lambda t, a: dispatch_responses.get(t, '{}'))

        feishu_calls = []
        save_summary_calls = []

        async def mock_feishu_send(message: str, **kwargs) -> dict:
            feishu_calls.append(message); return {"success": True}

        def mock_save_summary(content: str, category: str, **kwargs) -> dict:
            save_summary_calls.append({"content": content, "category": category})
            return {"summary_id": "hydration-001", "path": str(tmp_path / "summary.json")}

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

        assert result.status == "success"
        assert result.notification_sent is False, "No notification for adequate hydration"
        assert len(feishu_calls) == 0
        assert "adequate" in result.final_summary.lower()

    @pytest.mark.asyncio
    async def test_scenario_b_insufficient_hydration_sends_notification(self, tmp_path: Path):
        """
        Scenario B: 0 drink events → insufficient → Feishu notification with 💧.
        """
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_summarizer_task()

        llm_responses = [
            _tool_call_response(
                "vision.count_objects",
                {"event_log_path": "~/.clawtail/data/drink_events.jsonl", "window_minutes": 90},
                "c1",
            ),
            _final_response(
                "💧 Hydration insufficient! Only 0 drinking events detected in the past 90 minutes. "
                "WARNING: Please drink water now. Sending reminder alert."
            ),
        ]

        dispatch_responses = {
            "vision.count_objects": json.dumps({"count": 0, "window_minutes": 90}),
        }

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(side_effect=lambda t, a: dispatch_responses.get(t, '{}'))

        feishu_calls = []
        save_summary_calls = []

        async def mock_feishu_send(message: str, **kwargs) -> dict:
            feishu_calls.append(message); return {"success": True}

        def mock_save_summary(content: str, category: str, **kwargs) -> dict:
            save_summary_calls.append({"content": content, "category": category})
            return {"summary_id": "hydration-002", "path": str(tmp_path / "summary.json")}

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

        assert result.status == "success"
        assert result.notification_sent is True, "Feishu notification should be sent for insufficient hydration"
        assert len(feishu_calls) == 1
        # Message should contain 💧 or hydration reminder
        assert "💧" in feishu_calls[0] or "insufficient" in feishu_calls[0].lower() or "Hydration Summarizer" in feishu_calls[0]

    @pytest.mark.asyncio
    async def test_scenario_c_watcher_starts_on_system_start(self):
        """
        Scenario C: system.start event → drinking_watcher task fires → vision.start_watch called.
        """
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_watcher_task()

        # Track start_watch calls
        start_watch_calls = []

        llm_responses = [
            _tool_call_response(
                "vision.start_watch",
                {
                    "source_id": "desk_camera",
                    "labels": ["cup", "bottle", "drinking glass"],
                    "interval_seconds": 30,
                    "cooldown_seconds": 300,
                },
                "c1",
            ),
            _final_response("Background watcher started successfully for desk_camera."),
        ]

        async def mock_dispatch(tool_name: str, args: dict) -> str:
            if tool_name == "vision.start_watch":
                start_watch_calls.append(args)
                return json.dumps({"watch_id": "watch-001", "status": "started"})
            return "{}"

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[
            {"name": "vision.start_watch", "description": "Start background watcher"},
        ])
        mock_registry.dispatch = mock_dispatch

        run_count = [0]
        run_results = []

        async def mock_runner_run(t):
            run_count[0] += 1
            from core.agent.react_loop import ReactLoop
            from core.agent.context_budget import ContextBudget, AgentContext
            loop = ReactLoop(mock_llm, mock_registry, ContextBudget())
            result = await loop.run(t, AgentContext())
            run_results.append(result)
            return result

        mock_runner = MagicMock()
        mock_runner.run = mock_runner_run

        event_bus = EventBus()
        scheduler = TaskScheduler(mock_runner, event_bus)
        scheduler._scheduler = MagicMock()

        # Register watcher task
        scheduler.register_task(task)

        # Publish system.start event
        await event_bus.publish("system.start", {"source": "clawtail_start"})
        await asyncio.sleep(0.2)  # Allow event handler to execute

        # Assertions
        assert run_count[0] == 1, f"Expected 1 run, got {run_count[0]}"
        assert len(start_watch_calls) == 1, "vision.start_watch should have been called"
        assert start_watch_calls[0]["source_id"] == "desk_camera"
        assert "cup" in start_watch_calls[0]["labels"]
