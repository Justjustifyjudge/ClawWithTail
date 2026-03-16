"""
core.scheduler.scheduler — Task Scheduler (Cron + Event triggers).

Uses APScheduler AsyncIOScheduler for cron triggers.
Uses EventBus for event-driven triggers.

Trigger types:
  - cron: APScheduler CronTrigger, runs on schedule
  - on_event: EventBus subscription, runs when event fires
  - manual: No auto-trigger, only via run_now() or CLI
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Manages task scheduling via APScheduler (cron) and EventBus (events).

    Usage:
        scheduler = TaskScheduler(task_runner, event_bus)
        scheduler.load_tasks("~/.clawtail/tasks")
        scheduler.start()
        # ... later ...
        scheduler.stop()
    """

    def __init__(self, task_runner, event_bus) -> None:
        """
        Args:
            task_runner: TaskRunner instance.
            event_bus: EventBus instance.
        """
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        self._runner = task_runner
        self._event_bus = event_bus
        self._scheduler = AsyncIOScheduler()
        # Maps task_id → TaskConfig (for run_now and introspection)
        self._task_registry: dict[str, object] = {}

    def load_tasks(self, tasks_dir: str | None = None) -> int:
        """
        Scan tasks directory, load all .json files, and register each task.

        Args:
            tasks_dir: Path to tasks directory. Defaults to ~/.clawtail/tasks/

        Returns:
            Number of tasks successfully loaded.
        """
        from core.config import app_config
        from core.task_runner.loader import load_task, TaskLoadError

        if tasks_dir is None:
            base = Path(app_config.storage.base_dir).expanduser()
            tasks_dir = str(base / "tasks")

        tasks_path = Path(tasks_dir)
        if not tasks_path.exists():
            logger.info("TaskScheduler: tasks directory does not exist: %s", tasks_path)
            return 0

        loaded = 0
        for json_file in sorted(tasks_path.glob("*.json")):
            try:
                task = load_task(json_file)
                self.register_task(task)
                loaded += 1
                logger.info("TaskScheduler: loaded task '%s' from %s", task.task_id, json_file)
            except TaskLoadError as exc:
                logger.warning("TaskScheduler: failed to load %s: %s", json_file, exc)

        logger.info("TaskScheduler: loaded %d task(s) from %s", loaded, tasks_path)
        return loaded

    def register_task(self, task) -> None:
        """
        Register a task with the appropriate trigger mechanism.

        Args:
            task: TaskConfig instance.
        """
        self._task_registry[task.task_id] = task

        trigger_type = task.trigger.type

        if trigger_type == "cron":
            self._register_cron_task(task)
        elif trigger_type == "on_event":
            self._register_event_task(task)
        elif trigger_type == "manual":
            logger.info(
                "TaskScheduler: task '%s' is manual-only (no auto-trigger)", task.task_id
            )
        else:
            logger.warning(
                "TaskScheduler: unknown trigger type '%s' for task '%s'",
                trigger_type, task.task_id,
            )

    def _register_cron_task(self, task) -> None:
        """Register a cron-triggered task with APScheduler."""
        from apscheduler.triggers.cron import CronTrigger

        cron_expr = task.trigger.cron
        if not cron_expr:
            logger.warning(
                "TaskScheduler: cron task '%s' has no cron expression", task.task_id
            )
            return

        try:
            trigger = CronTrigger.from_crontab(cron_expr)
            self._scheduler.add_job(
                self._run_task_async,
                trigger=trigger,
                args=[task],
                id=task.task_id,
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info(
                "TaskScheduler: registered cron task '%s' with expression '%s'",
                task.task_id, cron_expr,
            )
        except Exception as exc:
            logger.warning(
                "TaskScheduler: failed to register cron task '%s': %s", task.task_id, exc
            )

    def _register_event_task(self, task) -> None:
        """Register an event-triggered task with EventBus."""
        event_pattern = task.trigger.event
        if not event_pattern:
            logger.warning(
                "TaskScheduler: event task '%s' has no event pattern", task.task_id
            )
            return

        def event_callback(event: str, data: dict) -> None:
            asyncio.create_task(self._run_task_async(task))

        self._event_bus.subscribe(event_pattern, event_callback)
        logger.info(
            "TaskScheduler: registered event task '%s' on pattern '%s'",
            task.task_id, event_pattern,
        )

    async def _run_task_async(self, task) -> None:
        """Wrapper to run a task and log errors."""
        try:
            await self._runner.run(task)
        except Exception as exc:
            logger.error(
                "TaskScheduler: task '%s' failed: %s", task.task_id, exc
            )

    def start(self) -> None:
        """Start the APScheduler and fire the system.start event."""
        self._scheduler.start()
        logger.info("TaskScheduler: started")

        # Fire system.start event asynchronously
        asyncio.create_task(
            self._event_bus.publish("system.start", {"source": "scheduler"})
        )

    def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        try:
            self._scheduler.shutdown(wait=False)
        except Exception as exc:
            logger.warning("TaskScheduler: error during shutdown: %s", exc)
        logger.info("TaskScheduler: stopped")

    async def run_now(self, task_id: str) -> "AgentRunResult":
        """
        Immediately trigger a task by ID (used by CLI `clawtail task run`).

        Args:
            task_id: The task_id to run.

        Returns:
            AgentRunResult

        Raises:
            KeyError: if task_id is not registered.
        """
        task = self._task_registry.get(task_id)
        if task is None:
            raise KeyError(
                f"TaskScheduler: task '{task_id}' not found. "
                f"Registered tasks: {list(self._task_registry.keys())}"
            )
        return await self._runner.run(task)

    def list_tasks(self) -> list[dict]:
        """Return a list of registered task summaries."""
        result = []
        for task_id, task in self._task_registry.items():
            result.append({
                "task_id": task_id,
                "name": task.name,
                "trigger_type": task.trigger.type,
                "trigger_value": task.trigger.cron or task.trigger.event or "manual",
                "description": task.description,
            })
        return result
