"""
core.agent.react_loop — ReAct (Reason + Act + Observe) orchestration loop.

Implements the core Agent execution cycle:
  1. REASON: LLM receives context + tool history, outputs thought + tool_call or final_answer
  2. ACT: ToolDispatcher routes tool_call to the correct MCP server
  3. OBSERVE: Tool result appended to tool_history, loop back to step 1

Termination conditions:
  - LLM outputs a final answer (no tool_calls in response)
  - step_count >= task.max_steps (default: 20)
  - Hard timeout: 10 minutes per run
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Hard timeout per run (seconds)
_RUN_TIMEOUT_SECONDS = 600  # 10 minutes


class ReactLoop:
    """
    ReAct orchestration loop.

    Drives the Reason → Act → Observe cycle until the LLM produces a
    final answer, the step limit is reached, or the timeout fires.
    """

    def __init__(self, llm_engine, tool_registry, budget) -> None:
        """
        Args:
            llm_engine: LLMEngine instance.
            tool_registry: ToolRegistry instance (provides get_all_tools + dispatch).
            budget: ContextBudget instance.
        """
        self._llm = llm_engine
        self._registry = tool_registry
        self._budget = budget

    async def run(self, task, context) -> "AgentRunResult":
        """
        Execute one full Agent run for the given task.

        Args:
            task: TaskConfig
            context: AgentContext (summaries + sensor_stats)

        Returns:
            AgentRunResult with status, tool_calls, final_summary.
        """
        from core.models.agent import AgentRunResult, ToolCallRecord

        run_id = str(uuid.uuid4())
        started_at = datetime.now(tz=timezone.utc)
        tool_history: list[dict] = []
        tool_call_records: list[ToolCallRecord] = []
        step_count = 0
        final_summary = ""
        status = "success"
        error: str | None = None

        # Fetch all available tools once
        try:
            all_tools = await self._registry.get_all_tools()
        except Exception as exc:
            logger.warning("ReactLoop: failed to get tools: %s", exc)
            all_tools = []

        try:
            async with asyncio.timeout(_RUN_TIMEOUT_SECONDS):
                while step_count < task.max_steps:
                    step_count += 1
                    logger.debug(
                        "ReactLoop: step %d/%d for task '%s'",
                        step_count, task.max_steps, task.task_id,
                    )

                    # ── REASON ────────────────────────────────────────────────
                    messages = self._budget.build_messages(task, context, tool_history)
                    response = await self._llm.complete(messages, tools=all_tools or None)
                    choice = response.choices[0]
                    message = choice.message

                    # ── Check for final answer ────────────────────────────────
                    if not message.tool_calls:
                        final_summary = message.content or ""
                        logger.info(
                            "ReactLoop: final answer at step %d for task '%s'",
                            step_count, task.task_id,
                        )
                        break

                    # ── ACT ───────────────────────────────────────────────────
                    # Record assistant message with tool_calls
                    tool_calls_raw = []
                    for tc in message.tool_calls:
                        tool_calls_raw.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })

                    tool_history.append({
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": tool_calls_raw,
                    })

                    # Execute each tool call
                    for tc in message.tool_calls:
                        tool_name = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}

                        call_start = time.monotonic()
                        try:
                            result_str = await self._registry.dispatch(tool_name, args)
                        except Exception as exc:
                            result_str = json.dumps({"error": str(exc)})
                            logger.warning(
                                "ReactLoop: tool '%s' failed: %s", tool_name, exc
                            )
                        duration_ms = int((time.monotonic() - call_start) * 1000)

                        # ── OBSERVE ───────────────────────────────────────────
                        tool_history.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_str,
                        })

                        tool_call_records.append(
                            ToolCallRecord(
                                tool_name=tool_name,
                                input_args=args,
                                output=result_str,
                                duration_ms=duration_ms,
                            )
                        )

                        logger.debug(
                            "ReactLoop: tool '%s' completed in %dms", tool_name, duration_ms
                        )
                else:
                    # Step limit reached
                    status = "step_limit_reached"
                    logger.warning(
                        "ReactLoop: step limit %d reached for task '%s'",
                        task.max_steps, task.task_id,
                    )

        except asyncio.TimeoutError:
            status = "failed"
            error = "timeout"
            logger.error(
                "ReactLoop: timeout after %ds for task '%s'",
                _RUN_TIMEOUT_SECONDS, task.task_id,
            )
        except Exception as exc:
            status = "failed"
            error = str(exc)
            logger.exception("ReactLoop: unexpected error for task '%s'", task.task_id)

        finished_at = datetime.now(tz=timezone.utc)
        return AgentRunResult(
            task_id=task.task_id,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            tool_calls=tool_call_records,
            final_summary=final_summary,
            error=error,
        )
