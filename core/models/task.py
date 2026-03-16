"""
Task configuration models — loaded from Task JSON files.
Corresponds to plan-01.md §2.3 and spec.md §3.2.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TriggerConfig:
    type: Literal["cron", "on_event", "manual"]
    cron: str | None = None           # cron expression, required when type=cron
    event: str | None = None          # e.g. "system.start", "device.push"
    event_source: str | None = None   # device_id or task_id


@dataclass
class SummaryContextConfig:
    category: str
    last_n: int = 5


@dataclass
class SensorStatsContextConfig:
    device_ids: list[str] = field(default_factory=list)
    window_minutes: int = 60


@dataclass
class ContextConfig:
    include_summaries: SummaryContextConfig | None = None
    include_sensor_stats: SensorStatsContextConfig | None = None


@dataclass
class OutputConfig:
    save_report: bool = False
    notify_feishu: bool = False
    notify_trigger: Literal["always", "on_anomaly", "on_complete"] = "on_complete"
    # Optional per-task Feishu webhook override
    feishu_webhook_url: str | None = None


@dataclass
class TaskConfig:
    task_id: str
    schema_version: str
    name: str
    description: str
    trigger: TriggerConfig
    goal: str
    context: ContextConfig = field(default_factory=ContextConfig)
    constraints: list[str] = field(default_factory=list)
    max_steps: int = 20
    output: OutputConfig = field(default_factory=OutputConfig)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for JSON persistence)."""
        return json.loads(json.dumps(self, default=_dataclass_default))


def _dataclass_default(obj):
    """JSON serializer for dataclasses."""
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
