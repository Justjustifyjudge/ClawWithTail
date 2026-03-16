"""
Unit tests for ReactLoop (T26 — Sprint 3 gate).
Tests: 2-step success, step limit, timeout.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_task(max_steps: int = 20):
    from core.models.task import TaskConfig, TriggerConfig
    return TaskConfig(
        task_id="test_task",
        schema_version="1.0",
        name="Test Task",
        description="Test",
        trigger=TriggerConfig(type="manual"),
        goal="Test goal",
        max_steps=max_steps,
    )


def _make_context():
    from core.agent.context_budget import AgentContext
    return AgentContext()


def _make_tool_call_response(tool_name: str, args: dict, call_id: str = "call_1"):
    """Create a mock LLM response with a tool call."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]

    choice = MagicMock()
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    return response


def _make_final_answer_response(text: str):
    """Create a mock LLM response with a final answer (no tool calls)."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None

    choice = MagicMock()
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    return response


class TestReactLoopSuccess:
    @pytest.mark.asyncio
    async def test_two_step_success(self):
        """
        ReactLoop completes in 2 steps:
          Step 1: LLM calls vision.capture_frame
          Step 2: LLM returns final answer
        """
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget

        mock_llm = MagicMock()
        mock_registry = MagicMock()
        budget = ContextBudget()

        # Step 1: tool call; Step 2: final answer
        mock_llm.complete = AsyncMock(side_effect=[
            _make_tool_call_response("vision.capture_frame", {"source_id": "desk_camera"}),
            _make_final_answer_response("Plant looks healthy. Soil moisture is adequate."),
        ])
        mock_registry.get_all_tools = AsyncMock(return_value=[
            {"name": "vision.capture_frame", "description": "Capture frame"}
        ])
        mock_registry.dispatch = AsyncMock(
            return_value='{"frame_path": "/tmp/frame.jpg", "timestamp": "2026-01-01T00:00:00"}'
        )

        loop = ReactLoop(mock_llm, mock_registry, budget)
        result = await loop.run(_make_task(), _make_context())

        assert result.status == "success"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "vision.capture_frame"
        assert "Plant looks healthy" in result.final_summary

    @pytest.mark.asyncio
    async def test_immediate_final_answer(self):
        """ReactLoop handles LLM returning final answer on step 1 (no tool calls)."""
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget

        mock_llm = MagicMock()
        mock_registry = MagicMock()
        budget = ContextBudget()

        mock_llm.complete = AsyncMock(return_value=_make_final_answer_response("Done."))
        mock_registry.get_all_tools = AsyncMock(return_value=[])

        loop = ReactLoop(mock_llm, mock_registry, budget)
        result = await loop.run(_make_task(), _make_context())

        assert result.status == "success"
        assert len(result.tool_calls) == 0
        assert result.final_summary == "Done."


class TestReactLoopStepLimit:
    @pytest.mark.asyncio
    async def test_step_limit_reached(self):
        """ReactLoop returns step_limit_reached when LLM never stops calling tools."""
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget

        mock_llm = MagicMock()
        mock_registry = MagicMock()
        budget = ContextBudget()

        # LLM always returns a tool call — never terminates
        mock_llm.complete = AsyncMock(
            return_value=_make_tool_call_response("vision.capture_frame", {"source_id": "cam"})
        )
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(return_value='{"frame_path": "/tmp/f.jpg"}')

        loop = ReactLoop(mock_llm, mock_registry, budget)
        result = await loop.run(_make_task(max_steps=3), _make_context())

        assert result.status == "step_limit_reached"
        assert len(result.tool_calls) == 3

    @pytest.mark.asyncio
    async def test_tool_dispatch_error_continues(self):
        """ReactLoop continues when a tool dispatch fails (records error in output)."""
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget

        mock_llm = MagicMock()
        mock_registry = MagicMock()
        budget = ContextBudget()

        mock_llm.complete = AsyncMock(side_effect=[
            _make_tool_call_response("vision.capture_frame", {"source_id": "cam"}),
            _make_final_answer_response("Completed despite tool error."),
        ])
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(side_effect=RuntimeError("Camera not found"))

        loop = ReactLoop(mock_llm, mock_registry, budget)
        result = await loop.run(_make_task(), _make_context())

        assert result.status == "success"
        assert len(result.tool_calls) == 1
        assert "error" in result.tool_calls[0].output.lower()


class TestReactLoopTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_failed(self):
        """ReactLoop returns status=failed with error=timeout on hard timeout."""
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget

        mock_llm = MagicMock()
        mock_registry = MagicMock()
        budget = ContextBudget()

        async def slow_complete(**kwargs):
            await asyncio.sleep(9999)

        mock_llm.complete = AsyncMock(side_effect=slow_complete)
        mock_registry.get_all_tools = AsyncMock(return_value=[])

        loop = ReactLoop(mock_llm, mock_registry, budget)

        # Patch the timeout to 0.1 seconds for testing
        with patch("core.agent.react_loop._RUN_TIMEOUT_SECONDS", 0.1):
            result = await loop.run(_make_task(), _make_context())

        assert result.status == "failed"
        assert result.error == "timeout"
