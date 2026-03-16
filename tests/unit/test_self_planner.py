"""
Unit tests for SelfPlanner (T29 — Sprint 3 gate).
Tests: JSON extraction, schema validation, retry on failure.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestExtractJsonFromText:
    def test_direct_json(self):
        """_extract_json_from_text parses direct JSON string."""
        from core.agent.self_planner import _extract_json_from_text
        text = '{"task_id": "test", "schema_version": "1.0"}'
        result = _extract_json_from_text(text)
        assert result["task_id"] == "test"

    def test_json_in_code_block(self):
        """_extract_json_from_text extracts JSON from ```json code block."""
        from core.agent.self_planner import _extract_json_from_text
        text = 'Here is the config:\n```json\n{"task_id": "test"}\n```\nDone.'
        result = _extract_json_from_text(text)
        assert result["task_id"] == "test"

    def test_json_embedded_in_text(self):
        """_extract_json_from_text extracts first {...} block from mixed text."""
        from core.agent.self_planner import _extract_json_from_text
        text = 'The task config is: {"task_id": "plant_monitor", "schema_version": "1.0"} and that is it.'
        result = _extract_json_from_text(text)
        assert result["task_id"] == "plant_monitor"

    def test_no_json_returns_none(self):
        """_extract_json_from_text returns None when no JSON found."""
        from core.agent.self_planner import _extract_json_from_text
        result = _extract_json_from_text("No JSON here at all.")
        assert result is None

    def test_invalid_json_returns_none(self):
        """_extract_json_from_text returns None for malformed JSON."""
        from core.agent.self_planner import _extract_json_from_text
        result = _extract_json_from_text("{invalid json}")
        assert result is None


class TestSelfPlannerPlan:
    @pytest.mark.asyncio
    async def test_plan_returns_valid_task_config(self):
        """SelfPlanner.plan returns a valid TaskConfig when LLM outputs valid JSON."""
        from core.agent.self_planner import SelfPlanner

        valid_task_json = {
            "task_id": "plant_monitor",
            "schema_version": "1.0",
            "name": "Plant Monitor",
            "description": "Monitor plant health",
            "trigger": {"type": "cron", "cron": "0 */2 * * *"},
            "goal": "Check plant soil moisture and health",
            "constraints": ["Do not water more than once per day"],
            "max_steps": 20,
            "context": {},
            "output": {"save_report": True, "notify_feishu": True, "notify_trigger": "on_anomaly"},
        }

        mock_result = MagicMock()
        mock_result.final_summary = json.dumps(valid_task_json)
        mock_result.status = "success"

        planner = SelfPlanner.__new__(SelfPlanner)
        planner._llm = MagicMock()
        planner._budget = MagicMock()
        planner._registry = MagicMock()
        planner._registry.get_all_tools = AsyncMock(return_value=[])
        planner._react_loop = MagicMock()
        planner._react_loop.run = AsyncMock(return_value=mock_result)

        with patch("core.agent.self_planner.SelfPlanner._save_task", return_value=MagicMock()):
            task_config = await planner.plan("Monitor my plant and remind me to water it")

        assert task_config.task_id == "plant_monitor"
        assert task_config.trigger.type == "cron"
        assert task_config.trigger.cron == "0 */2 * * *"

    @pytest.mark.asyncio
    async def test_plan_retries_on_invalid_json(self):
        """SelfPlanner.plan retries when LLM outputs invalid JSON on first attempt."""
        from core.agent.self_planner import SelfPlanner

        valid_task_json = {
            "task_id": "auto_retry_task",
            "schema_version": "1.0",
            "name": "Retry Task",
            "description": "Generated after retry",
            "trigger": {"type": "manual"},
            "goal": "Test goal",
            "context": {},
            "output": {},
        }

        # First attempt: invalid JSON; Second attempt: valid JSON
        mock_result_bad = MagicMock()
        mock_result_bad.final_summary = "I could not generate a valid config."
        mock_result_bad.status = "success"

        mock_result_good = MagicMock()
        mock_result_good.final_summary = json.dumps(valid_task_json)
        mock_result_good.status = "success"

        planner = SelfPlanner.__new__(SelfPlanner)
        planner._llm = MagicMock()
        planner._budget = MagicMock()
        planner._registry = MagicMock()
        planner._registry.get_all_tools = AsyncMock(return_value=[])
        planner._react_loop = MagicMock()
        planner._react_loop.run = AsyncMock(side_effect=[mock_result_bad, mock_result_good])

        with patch("core.agent.self_planner.SelfPlanner._save_task", return_value=MagicMock()):
            task_config = await planner.plan("Test goal")

        assert task_config.task_id == "auto_retry_task"
        assert planner._react_loop.run.call_count == 2

    @pytest.mark.asyncio
    async def test_plan_raises_after_max_retries(self):
        """SelfPlanner.plan raises ValueError after all retries fail."""
        from core.agent.self_planner import SelfPlanner

        mock_result_bad = MagicMock()
        mock_result_bad.final_summary = "No JSON here."
        mock_result_bad.status = "success"

        planner = SelfPlanner.__new__(SelfPlanner)
        planner._llm = MagicMock()
        planner._budget = MagicMock()
        planner._registry = MagicMock()
        planner._registry.get_all_tools = AsyncMock(return_value=[])
        planner._react_loop = MagicMock()
        planner._react_loop.run = AsyncMock(return_value=mock_result_bad)

        with pytest.raises(ValueError, match="failed to generate valid TaskConfig"):
            await planner.plan("Test goal")

    @pytest.mark.asyncio
    async def test_plan_auto_assigns_task_id(self):
        """SelfPlanner.plan auto-assigns task_id if missing from LLM output."""
        from core.agent.self_planner import SelfPlanner

        # JSON without task_id
        task_json_no_id = {
            "schema_version": "1.0",
            "name": "Auto Task",
            "description": "Auto-generated",
            "trigger": {"type": "manual"},
            "goal": "Test",
            "context": {},
            "output": {},
        }

        mock_result = MagicMock()
        mock_result.final_summary = json.dumps(task_json_no_id)
        mock_result.status = "success"

        planner = SelfPlanner.__new__(SelfPlanner)
        planner._llm = MagicMock()
        planner._budget = MagicMock()
        planner._registry = MagicMock()
        planner._registry.get_all_tools = AsyncMock(return_value=[])
        planner._react_loop = MagicMock()
        planner._react_loop.run = AsyncMock(return_value=mock_result)

        with patch("core.agent.self_planner.SelfPlanner._save_task", return_value=MagicMock()):
            task_config = await planner.plan("Test goal")

        # task_id should be auto-assigned
        assert task_config.task_id.startswith("auto_")
