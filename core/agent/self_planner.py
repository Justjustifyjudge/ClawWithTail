"""
core.agent.self_planner — Self-Planning Mode.

Runs a planning agent that uses knowledge tools to construct a TaskConfig JSON
from a natural language goal description.

Flow:
  1. Build planning prompt with TaskConfig JSON Schema
  2. Run ReactLoop (max 10 steps) with knowledge.* tools only
  3. Extract JSON from final_answer
  4. Validate against TaskConfig schema
  5. Retry once if validation fails
  6. Save to ~/.clawtail/tasks/{task_id}.json
  7. Return TaskConfig
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Planning agent is limited to these tools (no vision/sensor/notify)
_PLANNING_ALLOWED_TOOLS = {
    "knowledge.search_web",
    "knowledge.identify_plant",
    "knowledge.fetch_care_guide",
    "knowledge.search_local_kb",
    "storage.list_summaries",
}

# Minimal TaskConfig JSON Schema for the planning prompt
_TASK_SCHEMA_SUMMARY = """
{
  "task_id": "string (snake_case, unique)",
  "schema_version": "1.0",
  "name": "string (human-readable name)",
  "description": "string",
  "trigger": {
    "type": "cron | on_event | manual",
    "cron": "cron expression (required if type=cron, e.g. '0 */2 * * *')",
    "event": "event pattern (required if type=on_event, e.g. 'system.start')"
  },
  "goal": "string (what the agent should accomplish each run)",
  "constraints": ["list of constraint strings"],
  "max_steps": 20,
  "context": {
    "include_summaries": {"category": "string", "last_n": 5},
    "include_sensor_stats": {"device_ids": ["device_id"], "window_minutes": 60}
  },
  "output": {
    "save_report": true,
    "notify_feishu": true,
    "notify_trigger": "always | on_anomaly | on_complete"
  }
}
"""


def _extract_json_from_text(text: str) -> dict | None:
    """
    Extract a JSON object from text.

    Tries in order:
      1. Direct json.loads(text)
      2. Extract from ```json ... ``` code block
      3. Extract first {...} block with regex

    Returns:
        Parsed dict or None if extraction fails.
    """
    # 1. Direct parse
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Code block extraction
    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. First {...} block
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    return None


class SelfPlanner:
    """
    Planning agent that generates a TaskConfig from a natural language goal.

    Uses a restricted tool set (knowledge.* only) to research the goal
    and then synthesizes a valid TaskConfig JSON.
    """

    def __init__(self) -> None:
        from core.agent.llm_engine import get_llm_engine
        from core.agent.context_budget import ContextBudget
        from core.agent.tool_registry import ToolRegistry
        from core.agent.react_loop import ReactLoop

        self._llm = get_llm_engine()
        self._budget = ContextBudget()
        self._registry = ToolRegistry()
        self._react_loop = ReactLoop(self._llm, self._registry, self._budget)

    async def start(self) -> None:
        """Start knowledge and storage MCP servers for planning."""
        import sys
        servers = [
            ("knowledge", [sys.executable, "-m", "tools.knowledge.server"]),
            ("storage",   [sys.executable, "-m", "tools.storage.server"]),
        ]
        for name, cmd in servers:
            try:
                await self._registry.register_server(name, cmd)
            except Exception as exc:
                logger.warning("SelfPlanner: failed to start server '%s': %s", name, exc)

    async def stop(self) -> None:
        """Stop MCP servers."""
        await self._registry.stop()

    async def plan(self, goal: str) -> "TaskConfig":
        """
        Generate a TaskConfig from a natural language goal.

        Args:
            goal: Natural language description of what the task should do.

        Returns:
            Validated TaskConfig.

        Raises:
            ValueError: If a valid TaskConfig cannot be generated after retries.
        """
        from core.models.task import TaskConfig
        from core.task_runner.validator import validate_task
        from core.task_runner.loader import _dict_to_task_config
        from core.agent.context_budget import AgentContext

        # Build planning task
        planning_task = _make_planning_task(goal)
        context = AgentContext()

        # Filter tools to planning-allowed set
        original_get_all = self._registry.get_all_tools

        async def filtered_get_all():
            all_tools = await original_get_all()
            return [t for t in all_tools if t["name"] in _PLANNING_ALLOWED_TOOLS]

        self._registry.get_all_tools = filtered_get_all

        max_attempts = 2
        last_error: str = ""

        for attempt in range(max_attempts):
            try:
                result = await self._react_loop.run(planning_task, context)
                task_dict = _extract_json_from_text(result.final_summary)

                if task_dict is None:
                    last_error = "No JSON found in planning agent output"
                    logger.warning(
                        "SelfPlanner: attempt %d — %s", attempt + 1, last_error
                    )
                    continue

                # Ensure required fields
                if "task_id" not in task_dict:
                    task_dict["task_id"] = f"auto_{uuid.uuid4().hex[:8]}"
                if "schema_version" not in task_dict:
                    task_dict["schema_version"] = "1.0"

                is_valid, errors = validate_task(task_dict)
                if not is_valid:
                    last_error = f"Schema validation failed: {'; '.join(errors)}"
                    logger.warning(
                        "SelfPlanner: attempt %d — %s", attempt + 1, last_error
                    )
                    continue

                # Convert to TaskConfig and save
                task_config = _dict_to_task_config(task_dict)
                saved_path = self._save_task(task_dict)
                logger.info(
                    "SelfPlanner: generated task '%s' saved to %s",
                    task_config.task_id, saved_path,
                )
                return task_config

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "SelfPlanner: attempt %d failed: %s", attempt + 1, exc
                )

        raise ValueError(
            f"SelfPlanner: failed to generate valid TaskConfig after {max_attempts} attempts. "
            f"Last error: {last_error}"
        )

    def _save_task(self, task_dict: dict) -> Path:
        """Save generated TaskConfig JSON to ~/.clawtail/tasks/."""
        from core.config import app_config

        base_dir = Path(app_config.storage.base_dir).expanduser()
        tasks_dir = base_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        task_id = task_dict.get("task_id", f"auto_{uuid.uuid4().hex[:8]}")
        task_file = tasks_dir / f"{task_id}.json"
        task_file.write_text(
            json.dumps(task_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return task_file


def _make_planning_task(goal: str):
    """Create a synthetic TaskConfig for the planning agent."""
    from core.models.task import TaskConfig, TriggerConfig, ContextConfig, OutputConfig

    planning_goal = (
        f"You are a task planning assistant. Your job is to generate a TaskConfig JSON "
        f"for the following goal:\n\n\"{goal}\"\n\n"
        f"Use the knowledge tools to research the topic if needed. "
        f"Then output a complete, valid TaskConfig JSON that matches this schema:\n"
        f"{_TASK_SCHEMA_SUMMARY}\n\n"
        f"Your final answer MUST be a valid JSON object matching the schema above. "
        f"Do not include any text before or after the JSON object."
    )

    return TaskConfig(
        task_id="__planning__",
        schema_version="1.0",
        name="Self-Planning Task",
        description="Internal planning task",
        trigger=TriggerConfig(type="manual"),
        goal=planning_goal,
        constraints=[
            "Output ONLY a valid JSON object as your final answer",
            "Do not call vision, sensor, or notify tools",
            "Use knowledge tools to research the topic before generating the config",
        ],
        max_steps=10,
        context=ContextConfig(),
        output=OutputConfig(),
    )
