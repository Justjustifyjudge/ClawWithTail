"""
AgentRunResult — output of one complete Agent execution cycle.
Corresponds to plan-01.md §2.4.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class ToolCallRecord:
    tool_name: str
    input_args: dict
    output: Any
    duration_ms: int


@dataclass
class AgentRunResult:
    task_id: str
    run_id: str                    # UUID
    started_at: datetime
    finished_at: datetime
    status: Literal["success", "failed", "step_limit_reached"]
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_summary: str = ""        # LLM's final text output
    report_path: str | None = None
    notification_sent: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "status": self.status,
            "tool_calls": [
                {
                    "tool_name": tc.tool_name,
                    "input_args": tc.input_args,
                    "output": tc.output,
                    "duration_ms": tc.duration_ms,
                }
                for tc in self.tool_calls
            ],
            "final_summary": self.final_summary,
            "report_path": self.report_path,
            "notification_sent": self.notification_sent,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
