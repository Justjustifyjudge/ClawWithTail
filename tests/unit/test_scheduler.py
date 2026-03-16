"""
Unit tests for TaskScheduler (T28 — Sprint 3 gate).
Tests: cron trigger, event trigger, run_now.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.task import TaskConfig, TriggerConfig, ContextConfig, OutputConfig


def _make_cron_task(task_id="cron_task", cron="* * * * * *"):
    return TaskConfig(
        task_id=task_id,
        schema_version="1.0",
        name="Cron Task",
        description="Test cron task",
        trigger=TriggerConfig(type="cron", cron=cron),
        goal="Test",
    )


def _make_event_task(task_id="event_task", event="system.start"):
    return TaskConfig(
        task_id=task_id,
        schema_version="1.0",
        name="Event Task",
        description="Test event task",
        trigger=TriggerConfig(type="on_event", event=event),
        goal="Test",
    )


def _make_manual_task(task_id="manual_task"):
    return TaskConfig(
        task_id=task_id,
        schema_version="1.0",
        name="Manual Task",
        description="Test manual task",
        trigger=TriggerConfig(type="manual"),
        goal="Test",
    )


class TestSchedulerCronTrigger:
    @pytest.mark.asyncio
    async def test_cron_task_registered_with_apscheduler(self):
        """register_task adds a cron job to APScheduler."""
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus

        mock_runner = MagicMock()
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)
        mock_apscheduler = MagicMock()
        scheduler._scheduler = mock_apscheduler

        task = _make_cron_task(cron="0 */2 * * *")
        scheduler.register_task(task)

        mock_apscheduler.add_job.assert_called_once()
        call_kwargs = mock_apscheduler.add_job.call_args
        assert call_kwargs[1]["id"] == "cron_task"

    @pytest.mark.asyncio
    async def test_cron_task_fires_runner(self):
        """Cron task calls task_runner.run when triggered."""
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        mock_runner = MagicMock()
        run_count = [0]

        async def mock_run(task):
            run_count[0] += 1
            return MagicMock(status="success")

        mock_runner.run = mock_run
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)

        # Use interval trigger (every 0.1s) instead of cron for fast testing
        task = _make_cron_task()
        scheduler._task_registry[task.task_id] = task

        # Manually add job with interval trigger
        scheduler._scheduler.add_job(
            scheduler._run_task_async,
            trigger=IntervalTrigger(seconds=0.1),
            args=[task],
            id=task.task_id,
        )
        scheduler._scheduler.start()

        await asyncio.sleep(0.35)  # Wait for ~3 triggers
        scheduler.stop()

        assert run_count[0] >= 2, f"Expected >= 2 runs, got {run_count[0]}"


class TestSchedulerEventTrigger:
    @pytest.mark.asyncio
    async def test_event_task_fires_on_event(self):
        """Event task calls task_runner.run when matching event is published."""
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus

        mock_runner = MagicMock()
        run_count = [0]

        async def mock_run(task):
            run_count[0] += 1
            return MagicMock(status="success")

        mock_runner.run = mock_run
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)
        mock_apscheduler = MagicMock()
        scheduler._scheduler = mock_apscheduler

        task = _make_event_task(event="system.start")
        scheduler.register_task(task)

        # Publish the event
        await event_bus.publish("system.start", {"source": "test"})
        await asyncio.sleep(0.1)  # Allow asyncio.create_task to execute

        assert run_count[0] == 1

    @pytest.mark.asyncio
    async def test_event_task_wildcard_fires(self):
        """Event task with wildcard pattern fires on matching events."""
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus

        mock_runner = MagicMock()
        run_count = [0]

        async def mock_run(task):
            run_count[0] += 1
            return MagicMock(status="success")

        mock_runner.run = mock_run
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)
        mock_apscheduler = MagicMock()
        scheduler._scheduler = mock_apscheduler

        task = _make_event_task(event="device.push:*")
        scheduler.register_task(task)

        # Publish matching events
        await event_bus.publish("device.push:lab_temp_sensor", {})
        await event_bus.publish("device.push:plant_soil_sensor", {})
        await asyncio.sleep(0.1)

        assert run_count[0] == 2

    @pytest.mark.asyncio
    async def test_manual_task_not_auto_triggered(self):
        """Manual task is registered but not auto-triggered."""
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock()
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)
        mock_apscheduler = MagicMock()
        scheduler._scheduler = mock_apscheduler

        task = _make_manual_task()
        scheduler.register_task(task)

        # No auto-trigger — APScheduler should NOT have add_job called
        mock_apscheduler.add_job.assert_not_called()
        # But task should be in registry
        assert "manual_task" in scheduler._task_registry


class TestSchedulerRunNow:
    @pytest.mark.asyncio
    async def test_run_now_executes_task(self):
        """run_now immediately executes the specified task."""
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus

        mock_runner = MagicMock()
        mock_result = MagicMock(status="success")
        mock_runner.run = AsyncMock(return_value=mock_result)
        event_bus = EventBus()

        scheduler = TaskScheduler(mock_runner, event_bus)
        mock_apscheduler = MagicMock()
        scheduler._scheduler = mock_apscheduler

        task = _make_manual_task()
        scheduler.register_task(task)

        result = await scheduler.run_now("manual_task")

        mock_runner.run.assert_called_once_with(task)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_run_now_raises_for_unknown_task(self):
        """run_now raises KeyError for unknown task_id."""
        from core.scheduler.scheduler import TaskScheduler
        from core.scheduler.event_bus import EventBus

        mock_runner = MagicMock()
        event_bus = EventBus()
        scheduler = TaskScheduler(mock_runner, event_bus)
        scheduler._scheduler = MagicMock()

        with pytest.raises(KeyError, match="nonexistent_task"):
            await scheduler.run_now("nonexistent_task")
