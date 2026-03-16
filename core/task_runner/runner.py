"""
core.task_runner.runner — Task Runner: orchestrates a full task execution.

Responsibilities:
  1. Build AgentContext from TaskConfig.context settings
  2. Run the ReAct loop via ReactLoop
  3. Handle output policy (save_report, notify_feishu)
  4. Persist AgentRunResult to disk
  5. Fire task.complete:{task_id} event
"""
from __future__ import annotations

import logging
import uuid

from core.scheduler.event_bus import event_bus

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Orchestrates a complete task execution cycle.

    Usage:
        runner = TaskRunner()
        result = await runner.run(task_config)
    """

    def __init__(self) -> None:
        from core.agent.llm_engine import get_llm_engine
        from core.agent.context_budget import ContextBudget
        from core.agent.tool_registry import ToolRegistry
        from core.agent.react_loop import ReactLoop
        from core.task_runner.context_builder import ContextBuilder

        self._llm = get_llm_engine()
        self._budget = ContextBudget()
        self._registry = ToolRegistry()
        self._react_loop = ReactLoop(self._llm, self._registry, self._budget)
        self._context_builder = ContextBuilder()

    async def start(self) -> None:
        """Start MCP tool servers and register them in the ToolRegistry."""
        import sys
        servers = [
            ("vision",    [sys.executable, "-m", "tools.vision.server"]),
            ("sensor",    [sys.executable, "-m", "tools.sensor.server"]),
            ("storage",   [sys.executable, "-m", "tools.storage.server"]),
            ("notify",    [sys.executable, "-m", "tools.notify.server"]),
            ("knowledge", [sys.executable, "-m", "tools.knowledge.server"]),
        ]
        for name, cmd in servers:
            try:
                await self._registry.register_server(name, cmd)
            except Exception as exc:
                logger.warning("TaskRunner: failed to start MCP server '%s': %s", name, exc)

    async def stop(self) -> None:
        """Stop all MCP tool servers."""
        await self._registry.stop()

    async def run(self, task) -> "AgentRunResult":
        """
        Execute a complete task run.

        Steps:
          1. Build AgentContext
          2. Run ReAct loop
          3. Handle output policy (save_report, notify)
          4. Persist result
          5. Fire task.complete event

        Args:
            task: TaskConfig

        Returns:
            AgentRunResult
        """
        from core.task_runner.state import TaskRunState

        run_id = str(uuid.uuid4())
        state = TaskRunState(task_id=task.task_id, run_id=run_id)

        logger.info(
            "TaskRunner: starting run %s for task '%s'", run_id, task.task_id
        )

        # ── 1. Build context ──────────────────────────────────────────────────
        try:
            context = self._context_builder.build(task)
        except Exception as exc:
            logger.warning("TaskRunner: context build failed: %s", exc)
            from core.agent.context_budget import AgentContext
            context = AgentContext()

        # ── 2. Run ReAct loop ─────────────────────────────────────────────────
        result = await self._react_loop.run(task, context)
        result.run_id = run_id

        # ── 3. Handle output policy ───────────────────────────────────────────
        await self._handle_output_policy(task, result)

        # ── 4. Persist result ─────────────────────────────────────────────────
        try:
            state.save_result(result)
        except Exception as exc:
            logger.warning("TaskRunner: failed to save run result: %s", exc)

        # ── 5. Fire task.complete event ───────────────────────────────────────
        await event_bus.publish(
            f"task.complete:{task.task_id}",
            {"task_id": task.task_id, "run_id": run_id, "status": result.status},
        )

        logger.info(
            "TaskRunner: run %s for task '%s' finished with status '%s'",
            run_id, task.task_id, result.status,
        )
        return result

    async def _handle_output_policy(self, task, result) -> None:
        """Apply save_report and notify_feishu output policies."""
        # ── Save report ───────────────────────────────────────────────────────
        if task.output.save_report and result.final_summary:
            try:
                from tools.storage.server import _save_report
                save_result = _save_report(
                    content=result.final_summary,
                    title=task.name,
                    task_id=task.task_id,
                )
                result.report_path = save_result["report_path"]
                logger.info(
                    "TaskRunner: report saved to %s", result.report_path
                )
            except Exception as exc:
                logger.warning("TaskRunner: failed to save report: %s", exc)

        # ── Notify Feishu ─────────────────────────────────────────────────────
        if task.output.notify_feishu:
            should_notify = self._should_notify(task, result)
            if should_notify:
                try:
                    from tools.notify.server import _feishu_send_report, _feishu_send
                    if result.report_path:
                        await _feishu_send_report(
                            title=task.name,
                            summary=result.final_summary[:500],
                            report_path=result.report_path,
                        )
                    else:
                        await _feishu_send(
                            message=f"[{task.name}] {result.final_summary[:500]}"
                        )
                    result.notification_sent = True
                    logger.info("TaskRunner: Feishu notification sent")
                except Exception as exc:
                    logger.warning("TaskRunner: failed to send Feishu notification: %s", exc)

    @staticmethod
    def _should_notify(task, result) -> bool:
        """Determine whether to send a notification based on notify_trigger."""
        trigger = task.output.notify_trigger
        if trigger == "always":
            return True
        if trigger == "on_complete":
            return result.status == "success"
        if trigger == "on_anomaly":
            # Anomaly = final_summary contains anomaly keywords
            anomaly_keywords = [
                "anomaly", "alert", "warning", "critical", "error",
                "abnormal", "unusual", "danger", "urgent", "problem",
                "issue", "fail", "low", "high", "exceed",
            ]
            summary_lower = result.final_summary.lower()
            return any(kw in summary_lower for kw in anomaly_keywords)
        return False


# Global singleton — lazy-initialized
_runner: TaskRunner | None = None


def get_task_runner() -> TaskRunner:
    """Return the global TaskRunner singleton."""
    global _runner
    if _runner is None:
        _runner = TaskRunner()
    return _runner
