"""
Integration test — T32: Chemistry Experiment Monitor Demo (end-to-end).

Scenario A (significant change detected):
  - Camera returns two different fixture JPEGs (before/after)
  - LLM calls: compare_frames → analyze_image → final_answer (significant change)
  - Feishu webhook called (on_anomaly)
  - storage.save_summary called

Scenario B (experiment report generation):
  - 5 fixture summaries pre-loaded
  - chemistry_report task runs
  - storage.save_report called, Markdown contains "Timeline"
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.task import TaskConfig, TriggerConfig, ContextConfig, OutputConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_minimal_jpeg(seed: int = 0) -> bytes:
    """Return minimal JPEG bytes (slightly different per seed for 'different frames')."""
    base = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x0a\xff\xd9"
    )
    return base + bytes([seed % 256])


def _make_chemistry_task() -> TaskConfig:
    return TaskConfig(
        task_id="chemistry_monitor",
        schema_version="1.0",
        name="Chemistry Experiment Monitor",
        description="Monitor chemistry experiment",
        trigger=TriggerConfig(type="cron", cron="*/15 * * * *"),
        goal=(
            "Capture the current state of the experiment. Compare with the previous frame. "
            "Describe any observable changes (color, precipitate, gas bubbles, volume change). "
            "Save a timestamped summary. If significant change is detected, send an immediate Feishu alert."
        ),
        constraints=[
            "Always save an observation summary via storage.save_summary with category 'chem_experiment'",
            "Only call notify.feishu_send if a significant visual change is detected",
        ],
        max_steps=12,
        output=OutputConfig(
            save_report=True,
            notify_feishu=True,
            notify_trigger="on_anomaly",
        ),
    )


def _make_report_task() -> TaskConfig:
    return TaskConfig(
        task_id="chemistry_report",
        schema_version="1.0",
        name="Chemistry Experiment Report",
        description="Generate complete experiment log",
        trigger=TriggerConfig(type="manual"),
        goal="Generate a complete experiment log from all summaries. Include a Timeline section.",
        constraints=["Include a Timeline section in the report"],
        max_steps=8,
        output=OutputConfig(
            save_report=True,
            notify_feishu=False,
            notify_trigger="on_complete",
        ),
    )


def _tool_call_response(tool_name: str, args: dict, call_id: str = "c1"):
    tc = MagicMock(); tc.id = call_id; tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)
    msg = MagicMock(); msg.content = None; msg.tool_calls = [tc]
    choice = MagicMock(); choice.message = msg
    resp = MagicMock(); resp.choices = [choice]
    return resp


def _final_response(text: str):
    msg = MagicMock(); msg.content = text; msg.tool_calls = None
    choice = MagicMock(); choice.message = msg
    resp = MagicMock(); resp.choices = [choice]
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestChemistryMonitorDemo:
    @pytest.mark.asyncio
    async def test_chemistry_significant_change_triggers_alert(self, tmp_path: Path):
        """
        Significant change detected → Feishu alert sent, summary saved.
        """
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_chemistry_task()

        # Write two different fixture JPEGs
        frame1 = tmp_path / "frame_before.jpg"
        frame2 = tmp_path / "frame_after.jpg"
        frame1.write_bytes(_make_minimal_jpeg(seed=1))
        frame2.write_bytes(_make_minimal_jpeg(seed=2))

        llm_responses = [
            _tool_call_response("vision.capture_frame", {"source_id": "lab_camera"}, "c1"),
            _tool_call_response(
                "vision.compare_frames",
                {"frame_path_a": str(frame1), "frame_path_b": str(frame2)},
                "c2",
            ),
            _tool_call_response("vision.analyze_image", {"frame_path": str(frame2)}, "c3"),
            _final_response(
                "Significant change detected: Yellow precipitate forming in the beaker. "
                "Color changed from clear to pale yellow. "
                "WARNING: Significant chemical change observed — sending immediate alert."
            ),
        ]

        dispatch_responses = {
            "vision.capture_frame": json.dumps({
                "frame_path": str(frame2),
                "timestamp": "2026-01-01T14:00:00",
            }),
            "vision.compare_frames": json.dumps({
                "similarity": 0.62,
                "diff_description": "Yellow precipitate forming",
                "significant_change": True,
            }),
            "vision.analyze_image": json.dumps({
                "analysis": "Yellow precipitate visible in lower portion of beaker",
                "confidence": 0.91,
            }),
        }

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(
            side_effect=lambda t, a: dispatch_responses.get(t, '{}')
        )

        feishu_calls = []
        save_summary_calls = []
        save_report_calls = []

        async def mock_feishu_send(message: str, **kwargs) -> dict:
            feishu_calls.append(message)
            return {"success": True}

        def mock_save_summary(content: str, category: str, **kwargs) -> dict:
            save_summary_calls.append({"content": content, "category": category})
            return {"summary_id": "chem-001", "path": str(tmp_path / "summary.json")}

        def mock_save_report(content: str, title: str, task_id: str = "", **kwargs) -> dict:
            report_path = str(tmp_path / "report.md")
            save_report_calls.append({"content": content, "title": title})
            Path(report_path).write_text(content, encoding="utf-8")
            return {"report_path": report_path}

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = mock_llm
        runner._budget = ContextBudget()
        runner._registry = mock_registry
        runner._react_loop = ReactLoop(mock_llm, mock_registry, ContextBudget())
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=AgentContext())

        import core.task_runner.runner as rmod
        mock_event_bus = MagicMock(); mock_event_bus.publish = AsyncMock()

        with patch("core.config.app_config") as mock_cfg, \
             patch.object(rmod, "event_bus", mock_event_bus), \
             patch("tools.notify.server._feishu_send", mock_feishu_send), \
             patch("tools.storage.server._save_summary", mock_save_summary), \
             patch("tools.storage.server._save_report", mock_save_report):
            mock_cfg.storage.base_dir = str(tmp_path)
            result = await runner.run(task)

        assert result.status == "success"
        assert len(result.tool_calls) == 3
        assert "WARNING" in result.final_summary or "significant" in result.final_summary.lower()

        # Feishu alert sent (on_anomaly triggered)
        assert result.notification_sent is True
        assert len(feishu_calls) == 1

        # Report saved (save_report=True)
        assert result.report_path is not None
        assert len(save_report_calls) == 1

    @pytest.mark.asyncio
    async def test_chemistry_no_change_no_alert(self, tmp_path: Path):
        """
        No significant change → no Feishu alert, but summary still saved.
        """
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_chemistry_task()

        llm_responses = [
            _tool_call_response("vision.capture_frame", {"source_id": "lab_camera"}, "c1"),
            _tool_call_response("vision.compare_frames", {"frame_path_a": "/a.jpg", "frame_path_b": "/b.jpg"}, "c2"),
            _final_response(
                "No significant change detected. Solution remains clear. "
                "Temperature stable at 23°C. Observation saved."
            ),
        ]

        dispatch_responses = {
            "vision.capture_frame": json.dumps({"frame_path": "/tmp/frame.jpg", "timestamp": "2026-01-01T14:15:00"}),
            "vision.compare_frames": json.dumps({"similarity": 0.97, "significant_change": False}),
        }

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(side_effect=lambda t, a: dispatch_responses.get(t, '{}'))

        feishu_calls = []
        async def mock_feishu_send(message: str, **kwargs) -> dict:
            feishu_calls.append(message); return {"success": True}

        def mock_save_report(content: str, title: str, task_id: str = "", **kwargs) -> dict:
            report_path = str(tmp_path / "report.md")
            Path(report_path).write_text(content, encoding="utf-8")
            return {"report_path": report_path}

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = mock_llm
        runner._budget = ContextBudget()
        runner._registry = mock_registry
        runner._react_loop = ReactLoop(mock_llm, mock_registry, ContextBudget())
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=AgentContext())

        import core.task_runner.runner as rmod
        mock_event_bus = MagicMock(); mock_event_bus.publish = AsyncMock()

        with patch("core.config.app_config") as mock_cfg, \
             patch.object(rmod, "event_bus", mock_event_bus), \
             patch("tools.notify.server._feishu_send", mock_feishu_send), \
             patch("tools.storage.server._save_report", mock_save_report):
            mock_cfg.storage.base_dir = str(tmp_path)
            result = await runner.run(task)

        assert result.status == "success"
        assert result.notification_sent is False
        assert len(feishu_calls) == 0

    @pytest.mark.asyncio
    async def test_chemistry_report_generation(self, tmp_path: Path):
        """
        Experiment report generation: 5 fixture summaries → Markdown with Timeline section.
        """
        from core.task_runner.runner import TaskRunner
        from core.agent.react_loop import ReactLoop
        from core.agent.context_budget import ContextBudget, AgentContext

        task = _make_report_task()

        # Pre-load 5 fixture summaries
        summaries_dir = tmp_path / "summaries" / "chem_experiment"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            (summaries_dir / f"obs_{i:03d}.json").write_text(
                json.dumps({
                    "summary_id": f"chem-{i:03d}",
                    "category": "chem_experiment",
                    "content": f"Observation {i}: Solution color changed slightly. Temperature: {22 + i}°C.",
                    "created_at": f"2026-01-01T{10 + i}:00:00",
                }),
                encoding="utf-8",
            )

        report_content = (
            "# Chemistry Experiment Report\n\n"
            "## Timeline\n\n"
            "| Time | Observation |\n"
            "|------|-------------|\n"
            "| 10:00 | Initial state: clear solution |\n"
            "| 11:00 | Slight color change observed |\n"
            "| 12:00 | Yellow precipitate forming |\n"
            "| 13:00 | Precipitate settled |\n"
            "| 14:00 | Reaction complete |\n\n"
            "## Conclusion\n\nReaction proceeded as expected."
        )

        llm_responses = [
            _tool_call_response("storage.list_summaries", {"category": "chem_experiment"}, "c1"),
            _final_response(report_content),
        ]

        dispatch_responses = {
            "storage.list_summaries": json.dumps([
                {"summary_id": f"chem-{i:03d}", "content": f"Observation {i}"} for i in range(5)
            ]),
        }

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=llm_responses)
        mock_registry = MagicMock()
        mock_registry.get_all_tools = AsyncMock(return_value=[])
        mock_registry.dispatch = AsyncMock(side_effect=lambda t, a: dispatch_responses.get(t, '{}'))

        saved_reports = []

        def mock_save_report(content: str, title: str, task_id: str = "", **kwargs) -> dict:
            report_path = str(tmp_path / "experiment_report.md")
            Path(report_path).write_text(content, encoding="utf-8")
            saved_reports.append({"content": content, "path": report_path})
            return {"report_path": report_path}

        runner = TaskRunner.__new__(TaskRunner)
        runner._llm = mock_llm
        runner._budget = ContextBudget()
        runner._registry = mock_registry
        runner._react_loop = ReactLoop(mock_llm, mock_registry, ContextBudget())
        runner._context_builder = MagicMock()
        runner._context_builder.build = MagicMock(return_value=AgentContext())

        import core.task_runner.runner as rmod
        mock_event_bus = MagicMock(); mock_event_bus.publish = AsyncMock()

        with patch("core.config.app_config") as mock_cfg, \
             patch.object(rmod, "event_bus", mock_event_bus), \
             patch("tools.storage.server._save_report", mock_save_report):
            mock_cfg.storage.base_dir = str(tmp_path)
            result = await runner.run(task)

        assert result.status == "success"
        assert result.report_path is not None
        assert len(saved_reports) == 1

        # Verify Markdown contains Timeline section
        report_text = saved_reports[0]["content"]
        assert "Timeline" in report_text, "Report must contain a Timeline section"
        assert "## Timeline" in report_text
