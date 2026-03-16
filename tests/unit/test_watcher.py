"""
Unit tests for vision.start_watch / watcher loop (T24 — Sprint 2 gate).
Tests the _watch_loop coroutine with mocked camera and YOLO.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWatchLoop:
    @pytest.mark.asyncio
    async def test_detection_writes_event_to_jsonl(self, tmp_path: Path):
        """
        When _watch_loop detects a target label, it writes an event to the JSONL file.
        """
        event_log = str(tmp_path / "watch.jsonl")

        # Mock capture_frame to return a dummy path
        async def mock_capture(source_id, save_path=None):
            dummy = tmp_path / "frame.jpg"
            dummy.write_bytes(b"\xFF\xD8\xFF\xD9")
            return {"frame_path": str(dummy), "timestamp": "2026-01-01T00:00:00+00:00"}

        # Mock detect_objects to return "cup" detection
        async def mock_detect(frame_path, confidence=0.5):
            return [{"label": "cup", "confidence": 0.92, "bbox": [0, 0, 100, 100]}]

        with patch("tools.vision.watcher._capture_frame", mock_capture), \
             patch("tools.vision.watcher._detect_objects", mock_detect), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            # Make sleep raise CancelledError after first call to stop the loop
            call_count = [0]
            async def controlled_sleep(seconds):
                call_count[0] += 1
                if call_count[0] >= 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = controlled_sleep

            from tools.vision.watcher import _watch_loop
            try:
                await _watch_loop(
                    source_id="desk_camera",
                    labels=["cup"],
                    interval_seconds=30,
                    cooldown_seconds=300,
                    event_log_path=event_log,
                )
            except asyncio.CancelledError:
                pass

        # Verify event was written
        log_path = Path(event_log)
        assert log_path.exists(), "Event log file should be created"
        lines = [l for l in log_path.read_text(encoding="utf-8").strip().split("\n") if l]
        assert len(lines) >= 1
        event = json.loads(lines[0])
        assert "cup" in event["labels"]
        assert event["confidences"][0] == pytest.approx(0.92)

    @pytest.mark.asyncio
    async def test_no_detection_does_not_write_event(self, tmp_path: Path):
        """
        When no target label is detected, no event is written to the JSONL file.
        """
        event_log = str(tmp_path / "watch.jsonl")

        async def mock_capture(source_id, save_path=None):
            dummy = tmp_path / "frame.jpg"
            dummy.write_bytes(b"\xFF\xD8\xFF\xD9")
            return {"frame_path": str(dummy), "timestamp": "2026-01-01T00:00:00+00:00"}

        # No detections
        async def mock_detect(frame_path, confidence=0.5):
            return []

        call_count = [0]
        async def controlled_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 1:
                raise asyncio.CancelledError()

        with patch("tools.vision.watcher._capture_frame", mock_capture), \
             patch("tools.vision.watcher._detect_objects", mock_detect), \
             patch("asyncio.sleep", side_effect=controlled_sleep):
            from tools.vision.watcher import _watch_loop
            try:
                await _watch_loop(
                    source_id="desk_camera",
                    labels=["cup"],
                    interval_seconds=30,
                    cooldown_seconds=300,
                    event_log_path=event_log,
                )
            except asyncio.CancelledError:
                pass

        # No event should be written
        log_path = Path(event_log)
        if log_path.exists():
            lines = [l for l in log_path.read_text(encoding="utf-8").strip().split("\n") if l]
            assert len(lines) == 0

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate_events(self, tmp_path: Path):
        """
        After a detection, the loop sleeps for cooldown_seconds.
        Only one event is written per cooldown period.
        """
        event_log = str(tmp_path / "watch.jsonl")

        async def mock_capture(source_id, save_path=None):
            dummy = tmp_path / "frame.jpg"
            dummy.write_bytes(b"\xFF\xD8\xFF\xD9")
            return {"frame_path": str(dummy), "timestamp": "2026-01-01T00:00:00+00:00"}

        async def mock_detect(frame_path, confidence=0.5):
            return [{"label": "cup", "confidence": 0.85, "bbox": [0, 0, 50, 50]}]

        sleep_calls = []
        call_count = [0]

        async def controlled_sleep(seconds):
            sleep_calls.append(seconds)
            call_count[0] += 1
            if call_count[0] >= 2:
                raise asyncio.CancelledError()

        with patch("tools.vision.watcher._capture_frame", mock_capture), \
             patch("tools.vision.watcher._detect_objects", mock_detect), \
             patch("asyncio.sleep", side_effect=controlled_sleep):
            from tools.vision.watcher import _watch_loop
            try:
                await _watch_loop(
                    source_id="desk_camera",
                    labels=["cup"],
                    interval_seconds=30,
                    cooldown_seconds=300,
                    event_log_path=event_log,
                )
            except asyncio.CancelledError:
                pass

        # First sleep should be cooldown (300s), not interval (30s)
        assert sleep_calls[0] == 300, "First sleep after detection should be cooldown"


class TestStartStopWatch:
    @pytest.mark.asyncio
    async def test_start_watch_returns_watcher_id(self, tmp_path: Path):
        """start_watch returns a watcher_id and status=started."""
        from tools.vision.server import _start_watch, _stop_watch, _watchers

        async def mock_watch_loop(**kwargs):
            await asyncio.sleep(9999)

        with patch("tools.vision.server._watch_loop", mock_watch_loop):
            result = await _start_watch(
                source_id="desk_camera",
                labels=["cup"],
                interval_seconds=30,
                cooldown_seconds=300,
                event_log_path=str(tmp_path / "watch.jsonl"),
            )

        assert "watcher_id" in result
        assert result["status"] == "started"
        watcher_id = result["watcher_id"]

        # Cleanup
        await _stop_watch(watcher_id)

    @pytest.mark.asyncio
    async def test_stop_watch_cancels_task(self, tmp_path: Path):
        """stop_watch cancels the background task."""
        from tools.vision.server import _start_watch, _stop_watch, _watchers

        async def mock_watch_loop(**kwargs):
            await asyncio.sleep(9999)

        with patch("tools.vision.server._watch_loop", mock_watch_loop):
            start_result = await _start_watch(
                source_id="desk_camera",
                labels=["cup"],
                interval_seconds=30,
                cooldown_seconds=300,
                event_log_path=str(tmp_path / "watch.jsonl"),
            )

        watcher_id = start_result["watcher_id"]
        assert watcher_id in _watchers

        stop_result = await _stop_watch(watcher_id)
        assert stop_result["status"] == "stopped"
        assert watcher_id not in _watchers
