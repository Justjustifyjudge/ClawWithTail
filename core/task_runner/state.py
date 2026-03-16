"""
core.task_runner.state — Task run state persistence.

Maintains run metadata and persists AgentRunResult to disk.
Run logs are stored at: ~/.clawtail/logs/runs/{task_id}/{run_id}.json
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskRunState:
    """
    Manages the lifecycle state of a single task run and persists results.
    """

    def __init__(self, task_id: str, run_id: str) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.started_at: datetime = datetime.now(tz=timezone.utc)
        self.step_count: int = 0

    def save_result(self, result) -> Path:
        """
        Persist AgentRunResult to disk.

        Path: ~/.clawtail/logs/runs/{task_id}/{run_id}.json

        Args:
            result: AgentRunResult instance.

        Returns:
            Path to the saved file.
        """
        from core.config import app_config

        base_dir = Path(app_config.storage.base_dir).expanduser()
        run_dir = base_dir / "logs" / "runs" / self.task_id
        run_dir.mkdir(parents=True, exist_ok=True)

        run_file = run_dir / f"{self.run_id}.json"
        run_file.write_text(result.to_json(), encoding="utf-8")

        logger.debug(
            "TaskRunState: saved run result to %s (status=%s)",
            run_file, result.status,
        )
        return run_file
