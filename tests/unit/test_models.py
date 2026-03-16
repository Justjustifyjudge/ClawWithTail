"""
Unit tests for data models — serialization round-trip (T09 — Sprint 0 gate).
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from core.models import (
    AgentRunResult,
    BusMessage,
    BusPayload,
    TaskConfig,
    TriggerConfig,
    ToolCallRecord,
)


class TestBusMessageSerialization:
    def _make_frame_message(self) -> BusMessage:
        return BusMessage(
            device_id="desk_camera",
            device_type="camera",
            timestamp=datetime(2026, 3, 13, 10, 0, 0),
            payload=BusPayload(
                type="frame",
                data="/home/user/.clawtail/data/frames/desk_camera_20260313.jpg",
                unit=None,
                meta={"width": 1280, "height": 720},
            ),
        )

    def _make_reading_message(self) -> BusMessage:
        return BusMessage(
            device_id="plant_soil_sensor",
            device_type="sensor",
            timestamp=datetime(2026, 3, 13, 10, 0, 0),
            payload=BusPayload(type="reading", data=22.5, unit="percent"),
        )

    def test_frame_message_round_trip(self):
        msg = self._make_frame_message()
        restored = BusMessage.from_dict(msg.to_dict())
        assert restored.device_id == msg.device_id
        assert restored.device_type == msg.device_type
        assert restored.timestamp == msg.timestamp
        assert restored.payload.type == "frame"
        assert restored.payload.data == msg.payload.data
        assert restored.payload.meta == msg.payload.meta

    def test_reading_message_round_trip(self):
        msg = self._make_reading_message()
        restored = BusMessage.from_dict(msg.to_dict())
        assert restored.payload.data == 22.5
        assert restored.payload.unit == "percent"

    def test_jsonl_round_trip(self):
        msg = self._make_reading_message()
        line = msg.to_jsonl()
        assert "\n" not in line  # must be single line
        restored = BusMessage.from_jsonl(line)
        assert restored.device_id == msg.device_id
        assert restored.payload.data == msg.payload.data


class TestAgentRunResultSerialization:
    def test_to_json_is_valid_json(self):
        result = AgentRunResult(
            task_id="plant_monitor",
            run_id="abc-123",
            started_at=datetime(2026, 3, 13, 10, 0, 0),
            finished_at=datetime(2026, 3, 13, 10, 1, 0),
            status="success",
            tool_calls=[
                ToolCallRecord(
                    tool_name="vision.capture_frame",
                    input_args={"source_id": "desk_camera"},
                    output={"frame_path": "/tmp/frame.jpg"},
                    duration_ms=250,
                )
            ],
            final_summary="Plant looks healthy.",
        )
        json_str = result.to_json()
        parsed = json.loads(json_str)
        assert parsed["task_id"] == "plant_monitor"
        assert parsed["status"] == "success"
        assert len(parsed["tool_calls"]) == 1
        assert parsed["tool_calls"][0]["tool_name"] == "vision.capture_frame"


class TestImports:
    def test_all_models_importable(self):
        """Smoke test: all models can be imported from core.models."""
        from core.models import (
            AgentRunResult,
            BusMessage,
            BusPayload,
            EnvProfile,
            ContextConfig,
            OutputConfig,
            SensorStatsContextConfig,
            SummaryContextConfig,
            TaskConfig,
            TriggerConfig,
            ToolCallRecord,
        )
        assert AgentRunResult is not None
        assert BusMessage is not None
