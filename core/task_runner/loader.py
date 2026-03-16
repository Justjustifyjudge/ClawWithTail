"""
Task loader — reads a Task JSON file, validates it, and returns a TaskConfig.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.models.task import (
    ContextConfig,
    OutputConfig,
    SensorStatsContextConfig,
    SummaryContextConfig,
    TaskConfig,
    TriggerConfig,
)
from core.task_runner.validator import validate_task


class TaskLoadError(Exception):
    """Raised when a Task JSON file fails to load or validate."""


def load_task(path: str | Path) -> TaskConfig:
    """
    Load and validate a Task JSON file.

    Raises:
        TaskLoadError: if the file cannot be read or fails schema validation.
    """
    task_path = Path(path)
    if not task_path.exists():
        raise TaskLoadError(f"Task file not found: {task_path}")

    try:
        raw = json.loads(task_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskLoadError(f"Invalid JSON in {task_path}: {exc}") from exc

    is_valid, errors = validate_task(raw)
    if not is_valid:
        error_str = "\n  ".join(errors)
        raise TaskLoadError(f"Task validation failed for {task_path}:\n  {error_str}")

    return _dict_to_task_config(raw)


def _dict_to_task_config(d: dict) -> TaskConfig:
    trigger_raw = d["trigger"]
    trigger = TriggerConfig(
        type=trigger_raw["type"],
        cron=trigger_raw.get("cron"),
        event=trigger_raw.get("event"),
        event_source=trigger_raw.get("event_source"),
    )

    context_raw = d.get("context", {})
    summaries_raw = context_raw.get("include_summaries")
    sensor_raw = context_raw.get("include_sensor_stats")
    context = ContextConfig(
        include_summaries=(
            SummaryContextConfig(
                category=summaries_raw["category"],
                last_n=summaries_raw.get("last_n", 5),
            )
            if summaries_raw
            else None
        ),
        include_sensor_stats=(
            SensorStatsContextConfig(
                device_ids=sensor_raw["device_ids"],
                window_minutes=sensor_raw.get("window_minutes", 60),
            )
            if sensor_raw
            else None
        ),
    )

    output_raw = d.get("output", {})
    output = OutputConfig(
        save_report=output_raw.get("save_report", False),
        notify_feishu=output_raw.get("notify_feishu", False),
        notify_trigger=output_raw.get("notify_trigger", "on_complete"),
        feishu_webhook_url=output_raw.get("feishu_webhook_url"),
    )

    return TaskConfig(
        task_id=d["task_id"],
        schema_version=d["schema_version"],
        name=d["name"],
        description=d["description"],
        trigger=trigger,
        goal=d["goal"],
        context=context,
        constraints=d.get("constraints", []),
        max_steps=d.get("max_steps", 20),
        output=output,
    )
