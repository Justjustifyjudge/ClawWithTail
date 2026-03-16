"""
core.scheduler — Scheduler package.
Exposes global task_scheduler singleton.
"""
from __future__ import annotations

from core.scheduler.event_bus import event_bus

# Lazy singleton — initialized on first access
_task_scheduler = None


def get_task_scheduler():
    """Return the global TaskScheduler singleton."""
    global _task_scheduler
    if _task_scheduler is None:
        from core.scheduler.scheduler import TaskScheduler
        from core.task_runner.runner import get_task_runner
        _task_scheduler = TaskScheduler(get_task_runner(), event_bus)
    return _task_scheduler
