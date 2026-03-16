"""
Integration tests for vision tools pipeline (T24 — Sprint 2 gate).
Tests capture_frame → analyze_image chain with mocked cv2 and LiteLLM.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestVisionCapturePipeline:
    @pytest.mark.asyncio
    async def test_capture_frame_returns_valid_path(self, tmp_path: Path):
        """capture_frame returns a frame_path that points to an existing file."""
        from tools.vision.server import _capture_frame
        from adapters.camera.mock import MockCameraAdapter

        mock_adapter = MockCameraAdapter(
            MagicMock(id="desk_camera", type="camera", transport="usb", source="0"),
            MagicMock(os="linux", camera_backend="none"),
        )

        with patch("tools.vision.server.camera_registry") as mock_registry, \
             patch("tools.vision.server.init_storage", return_value=tmp_path):
            mock_registry.get.return_value = mock_adapter
            result = await _capture_frame("desk_camera", save_path=None)

        assert "frame_path" in result
        assert "timestamp" in result
        assert Path(result["frame_path"]).exists()

    @pytest.mark.asyncio
    async def test_analyze_image_no_base64_in_response(self, tmp_path: Path):
        """analyze_image response does NOT contain base64 image data."""
        from tools.vision.server import _analyze_image

        # Create a dummy JPEG file
        frame_path = tmp_path / "test_frame.jpg"
        frame_path.write_bytes(b"\xFF\xD8\xFF\xD9")  # Minimal JPEG

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "The plant looks healthy with green leaves."

        mock_cfg = MagicMock()
        mock_cfg.vision_model = "gpt-4o"

        with patch("tools.vision.server.litellm") as mock_litellm, \
             patch("tools.vision.server.get_tool_config", return_value=mock_cfg):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await _analyze_image(str(frame_path), "Describe the plant health.")

        assert "analysis_text" in result
        assert result["analysis_text"] == "The plant looks healthy with green leaves."

        # CRITICAL: base64 data must NOT be in the response
        result_str = json.dumps(result)
        assert "data:image" not in result_str
        assert len(result_str) < 10000  # Response should be small (no base64)

    @pytest.mark.asyncio
    async def test_count_objects_from_event_log(self, tmp_path: Path):
        """count_objects correctly counts events from a JSONL log."""
        from tools.vision.server import _count_objects
        from datetime import datetime, timedelta, timezone

        event_log = tmp_path / "watch.jsonl"
        now = datetime.now(tz=timezone.utc)

        # Write 3 events within the last 60 minutes
        events = [
            {"timestamp": (now - timedelta(minutes=10)).isoformat(), "labels": ["cup"], "confidences": [0.9]},
            {"timestamp": (now - timedelta(minutes=30)).isoformat(), "labels": ["cup"], "confidences": [0.85]},
            {"timestamp": (now - timedelta(minutes=90)).isoformat(), "labels": ["cup"], "confidences": [0.8]},  # Outside window
        ]
        with open(event_log, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        result = await _count_objects(str(event_log), "cup", window_minutes=60)

        assert result["count"] == 2  # Only 2 within 60 minutes
        assert result["label"] == "cup"
        assert result["window_minutes"] == 60


class TestVisionWatcherPipeline:
    @pytest.mark.asyncio
    async def test_start_watch_stop_watch_lifecycle(self, tmp_path: Path):
        """start_watch creates a task; stop_watch cancels it."""
        from tools.vision.server import _start_watch, _stop_watch, _watchers

        async def mock_watch_loop(**kwargs):
            try:
                await asyncio.sleep(9999)
            except asyncio.CancelledError:
                pass

        import asyncio
        with patch("tools.vision.server._watch_loop", mock_watch_loop), \
             patch("tools.vision.server.init_storage", return_value=tmp_path):
            start_result = await _start_watch(
                source_id="desk_camera",
                labels=["cup"],
                interval_seconds=30,
                cooldown_seconds=300,
                event_log_path=str(tmp_path / "watch.jsonl"),
            )

        watcher_id = start_result["watcher_id"]
        assert start_result["status"] == "started"
        assert watcher_id in _watchers

        stop_result = await _stop_watch(watcher_id)
        assert stop_result["status"] == "stopped"
        assert watcher_id not in _watchers
