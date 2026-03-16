"""
core.task_runner.context_builder — Builds AgentContext from TaskConfig.

Fetches summaries and sensor stats according to the task's context config,
then assembles an AgentContext ready for injection into the LLM context window.
"""
from __future__ import annotations

import logging

from core.agent.context_budget import AgentContext
from core.models.task import TaskConfig

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Builds an AgentContext by fetching summaries and sensor stats
    as specified in the TaskConfig.context settings.
    """

    def build(self, task: TaskConfig) -> AgentContext:
        """
        Build AgentContext for a task run.

        Fetches:
          - Recent summaries (text only, no images) if include_summaries is set
          - Sensor stats (aggregated numbers) if include_sensor_stats is set

        Args:
            task: TaskConfig with context configuration.

        Returns:
            AgentContext ready for ContextBudget.build_messages().
        """
        context = AgentContext()

        # ── Inject recent summaries ───────────────────────────────────────────
        if task.context.include_summaries:
            cfg = task.context.include_summaries
            try:
                from tools.storage.server import _list_summaries, _read_summary
                summaries_meta = _list_summaries(
                    category=cfg.category,
                    last_n=cfg.last_n,
                )
                for meta in summaries_meta:
                    try:
                        record = _read_summary(meta["summary_id"])
                        context.summaries.append(record["content"])
                    except Exception as exc:
                        logger.warning(
                            "ContextBuilder: failed to read summary %s: %s",
                            meta["summary_id"], exc,
                        )
            except Exception as exc:
                logger.warning(
                    "ContextBuilder: failed to list summaries for category '%s': %s",
                    cfg.category, exc,
                )

        # ── Inject sensor stats ───────────────────────────────────────────────
        if task.context.include_sensor_stats:
            cfg = task.context.include_sensor_stats
            from datetime import datetime, timedelta, timezone
            now = datetime.now(tz=timezone.utc)
            from_iso = (now - timedelta(minutes=cfg.window_minutes)).isoformat()
            to_iso = now.isoformat()

            for device_id in cfg.device_ids:
                try:
                    from core.bus.bus import DeviceDataBus
                    from core.bus import bus
                    stats = bus.get_stats(device_id, from_iso, to_iso)
                    context.sensor_stats[device_id] = stats
                except Exception as exc:
                    logger.warning(
                        "ContextBuilder: failed to get stats for device '%s': %s",
                        device_id, exc,
                    )

        return context
