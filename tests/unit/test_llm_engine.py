"""
Unit tests for LLMEngine (T25 — Sprint 3 gate).
Tests 429 retry logic and vision call.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


class TestLLMEngineRetry:
    @pytest.mark.asyncio
    async def test_429_triggers_retry_and_succeeds(self):
        """LLMEngine retries on 429 and succeeds on second attempt."""
        from core.agent.llm_engine import LLMEngine

        call_count = [0]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello"
        mock_response.choices[0].message.tool_calls = None

        async def mock_acompletion(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("429 rate limit exceeded")
            return mock_response

        engine = LLMEngine.__new__(LLMEngine)
        engine._cfg = MagicMock()
        engine._default_model = "gpt-4o"
        engine._vision_model = "gpt-4o"
        engine._fallback_model = "gpt-4o-mini"

        with patch("core.agent.llm_engine.asyncio.sleep", new_callable=AsyncMock), \
             patch("litellm.acompletion", side_effect=mock_acompletion):
            result = await engine.complete([{"role": "user", "content": "test"}])

        assert call_count[0] == 2
        assert result == mock_response

    @pytest.mark.asyncio
    async def test_429_max_retries_exhausted_raises(self):
        """LLMEngine raises after max retries (3) on persistent 429."""
        from core.agent.llm_engine import LLMEngine

        call_count = [0]

        async def mock_acompletion(**kwargs):
            call_count[0] += 1
            raise Exception("429 Too Many Requests")

        engine = LLMEngine.__new__(LLMEngine)
        engine._cfg = MagicMock()
        engine._default_model = "gpt-4o"
        engine._vision_model = "gpt-4o"
        engine._fallback_model = "gpt-4o-mini"

        with patch("core.agent.llm_engine.asyncio.sleep", new_callable=AsyncMock), \
             patch("litellm.acompletion", side_effect=mock_acompletion):
            with pytest.raises(Exception, match="429"):
                await engine.complete([{"role": "user", "content": "test"}])

        # 1 initial + 3 retries = 4 total calls
        assert call_count[0] == 4

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_not_retried(self):
        """LLMEngine does NOT retry on non-429 errors."""
        from core.agent.llm_engine import LLMEngine

        call_count = [0]

        async def mock_acompletion(**kwargs):
            call_count[0] += 1
            raise ValueError("Invalid model name")

        engine = LLMEngine.__new__(LLMEngine)
        engine._cfg = MagicMock()
        engine._default_model = "gpt-4o"
        engine._vision_model = "gpt-4o"
        engine._fallback_model = "gpt-4o-mini"

        with patch("litellm.acompletion", side_effect=mock_acompletion):
            with pytest.raises(ValueError, match="Invalid model name"):
                await engine.complete([{"role": "user", "content": "test"}])

        # Only 1 call — no retry for non-429
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_complete_passes_tools_to_litellm(self):
        """LLMEngine passes tools parameter to litellm when provided."""
        from core.agent.llm_engine import LLMEngine

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"
        mock_response.choices[0].message.tool_calls = None

        engine = LLMEngine.__new__(LLMEngine)
        engine._cfg = MagicMock()
        engine._default_model = "gpt-4o"
        engine._vision_model = "gpt-4o"
        engine._fallback_model = "gpt-4o-mini"

        tools = [{"name": "vision.capture_frame", "description": "Capture a frame"}]

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
            await engine.complete([{"role": "user", "content": "test"}], tools=tools)

        call_kwargs = mock_llm.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == tools
        assert call_kwargs["tool_choice"] == "auto"


class TestContextBudget:
    def test_estimate_tokens(self):
        """estimate_tokens returns character_count / 4."""
        from core.agent.context_budget import ContextBudget
        budget = ContextBudget()
        assert budget.estimate_tokens("hello") == 1  # 5 chars / 4 = 1
        assert budget.estimate_tokens("a" * 400) == 100

    def test_truncate_to_budget_no_truncation(self):
        """truncate_to_budget returns text unchanged when within budget."""
        from core.agent.context_budget import ContextBudget
        budget = ContextBudget()
        text = "Short text"
        result = budget.truncate_to_budget(text, max_tokens=100)
        assert result == text

    def test_truncate_to_budget_truncates(self):
        """truncate_to_budget truncates and appends ...[truncated]."""
        from core.agent.context_budget import ContextBudget
        budget = ContextBudget()
        long_text = "x" * 1000
        result = budget.truncate_to_budget(long_text, max_tokens=10)
        assert result.endswith("...[truncated]")
        assert len(result) <= 10 * 4 + 20  # max_chars + truncation suffix

    def test_build_messages_includes_goal(self):
        """build_messages includes the task goal in the system message."""
        from core.agent.context_budget import ContextBudget, AgentContext
        from core.models.task import TaskConfig, TriggerConfig, ContextConfig, OutputConfig

        budget = ContextBudget()
        task = TaskConfig(
            task_id="test",
            schema_version="1.0",
            name="Test Task",
            description="Test",
            trigger=TriggerConfig(type="manual"),
            goal="Monitor the plant and check soil moisture",
            constraints=["Do not water more than once per day"],
        )
        context = AgentContext()
        messages = budget.build_messages(task, context, [])

        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "Monitor the plant" in system_msg["content"]
        assert "Do not water more than once per day" in system_msg["content"]

    def test_build_messages_injects_summaries(self):
        """build_messages injects summaries into system message."""
        from core.agent.context_budget import ContextBudget, AgentContext
        from core.models.task import TaskConfig, TriggerConfig, ContextConfig, OutputConfig

        budget = ContextBudget()
        task = TaskConfig(
            task_id="test", schema_version="1.0", name="Test", description="",
            trigger=TriggerConfig(type="manual"), goal="Test goal",
        )
        context = AgentContext(summaries=["Plant was healthy yesterday.", "Soil moisture was 45%."])
        messages = budget.build_messages(task, context, [])

        system_content = messages[0]["content"]
        assert "Plant was healthy yesterday." in system_content
        assert "Soil moisture was 45%." in system_content

    def test_build_messages_first_step_has_begin(self):
        """build_messages adds 'Begin.' user message when tool_history is empty."""
        from core.agent.context_budget import ContextBudget, AgentContext
        from core.models.task import TaskConfig, TriggerConfig

        budget = ContextBudget()
        task = TaskConfig(
            task_id="test", schema_version="1.0", name="Test", description="",
            trigger=TriggerConfig(type="manual"), goal="Test goal",
        )
        context = AgentContext()
        messages = budget.build_messages(task, context, [])

        assert len(messages) == 2
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Begin."
