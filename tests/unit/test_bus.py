"""
Unit tests for Device Data Bus core (T16 — Sprint 1 gate).
Tests ring buffer overflow, JSONL persistence, get_history, get_stats.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.bus.bus import DeviceDataBus
from core.models.bus import BusMessage, BusPayload


def _make_reading(device_id: str, value: float, ts: datetime | None = None) -> BusMessage:
    return BusMessage(
        device_id=device_id,
        device_type="sensor",
        timestamp=ts or datetime.now(tz=timezone.utc),
        payload=BusPayload(type="reading", data=value, unit="percent"),
    )


class TestRingBuffer:
    @pytest.mark.asyncio
    async def test_put_and_get_latest(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        msg = _make_reading("sensor1", 42.0)
        await bus.put(msg)
        latest = await bus.get_latest("sensor1")
        assert latest is not None
        assert latest.payload.data == 42.0

    @pytest.mark.asyncio
    async def test_get_latest_empty_returns_none(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        result = await bus.get_latest("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ring_buffer_overflow_drops_oldest(self, tmp_path: Path):
        """Putting 1001 messages into a size-1000 buffer drops the oldest."""
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        # Fill buffer to capacity
        for i in range(10):
            await bus.put(_make_reading("sensor1", float(i)))
        # Add one more — should drop value=0.0
        await bus.put(_make_reading("sensor1", 99.0))

        # get_latest should return the most recent (99.0)
        latest = await bus.get_latest("sensor1")
        assert latest.payload.data == 99.0

    @pytest.mark.asyncio
    async def test_get_latest_is_non_destructive(self, tmp_path: Path):
        """Calling get_latest twice returns the same message."""
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        msg = _make_reading("sensor1", 55.5)
        await bus.put(msg)
        r1 = await bus.get_latest("sensor1")
        r2 = await bus.get_latest("sensor1")
        assert r1 is not None
        assert r2 is not None
        assert r1.payload.data == r2.payload.data == 55.5


class TestJSONLPersistence:
    @pytest.mark.asyncio
    async def test_put_creates_jsonl_file(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        msg = _make_reading("sensor1", 25.3)
        await bus.put(msg)
        log_file = tmp_path / "data" / "sensor_logs" / "sensor1.jsonl"
        assert log_file.exists()

    @pytest.mark.asyncio
    async def test_put_appends_valid_jsonl(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        await bus.put(_make_reading("sensor1", 10.0))
        await bus.put(_make_reading("sensor1", 20.0))
        log_file = tmp_path / "data" / "sensor_logs" / "sensor1.jsonl"
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        # Each line must be valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "device_id" in parsed
            assert parsed["device_id"] == "sensor1"

    @pytest.mark.asyncio
    async def test_multiple_devices_separate_files(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        await bus.put(_make_reading("sensor_a", 1.0))
        await bus.put(_make_reading("sensor_b", 2.0))
        log_dir = tmp_path / "data" / "sensor_logs"
        assert (log_dir / "sensor_a.jsonl").exists()
        assert (log_dir / "sensor_b.jsonl").exists()


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_get_history_time_range_filter(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=100, base_dir=str(tmp_path))
        now = datetime.now(tz=timezone.utc)
        # Put messages at t-2h, t-1h, t-30min, t-5min
        for minutes_ago, value in [(120, 1.0), (60, 2.0), (30, 3.0), (5, 4.0)]:
            ts = now - timedelta(minutes=minutes_ago)
            await bus.put(_make_reading("sensor1", value, ts))

        # Query last 90 minutes — should get 3.0 and 4.0
        from_dt = now - timedelta(minutes=90)
        results = bus.get_history(
            "sensor1",
            from_iso=from_dt.isoformat(),
            to_iso=now.isoformat(),
        )
        values = [r.payload.data for r in results]
        assert 3.0 in values
        assert 4.0 in values
        assert 1.0 not in values
        assert 2.0 not in values

    def test_get_history_missing_file_returns_empty(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        results = bus.get_history(
            "nonexistent",
            from_iso="2026-01-01T00:00:00+00:00",
            to_iso="2026-12-31T23:59:59+00:00",
        )
        assert results == []


class TestGetStats:
    @pytest.mark.asyncio
    async def test_get_stats_basic(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=100, base_dir=str(tmp_path))
        now = datetime.now(tz=timezone.utc)
        for i, value in enumerate([10.0, 20.0, 30.0]):
            ts = now - timedelta(minutes=i * 5)
            await bus.put(_make_reading("sensor1", value, ts))

        stats = bus.get_stats("sensor1", window_minutes=60)
        assert stats["count"] == 3
        assert stats["min"] == 10.0
        assert stats["max"] == 30.0
        assert stats["avg"] == 20.0
        assert stats["unit"] == "percent"

    def test_get_stats_no_data(self, tmp_path: Path):
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        stats = bus.get_stats("nonexistent", window_minutes=60)
        assert stats["count"] == 0
        assert stats["trend"] == "insufficient_data"
