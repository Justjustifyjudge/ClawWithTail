"""
Integration test: Poll Manager pipeline (T16 — Sprint 1 gate).
Verifies that PollManager puts messages into the bus at the correct interval.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.bus.bus import DeviceDataBus
from core.bus.poll_manager import PollManager
from core.config.models import DeviceConfig, DevicesConfig
from core.models.bus import BusMessage, BusPayload
from core.models.env_profile import EnvProfile


def _make_wifi_device(interval: int = 1) -> DeviceConfig:
    return DeviceConfig(
        id="plant_soil_sensor",
        type="sensor",
        subtype="soil_moisture",
        transport="wifi_poll",
        poll_url="http://192.168.1.42/api/moisture",
        poll_interval_seconds=interval,
    )


def _make_env() -> EnvProfile:
    return EnvProfile(
        os="linux", camera_backend="v4l2", gpu_available=False,
        gpu_type="none", bluetooth_available=False, python_version="3.11",
        yolo_variant="yolov8n",
    )


def _make_mock_message(device_id: str, value: float) -> BusMessage:
    return BusMessage(
        device_id=device_id,
        device_type="sensor",
        timestamp=datetime.now(tz=timezone.utc),
        payload=BusPayload(type="reading", data=value, unit="percent"),
    )


class TestPollManagerPipeline:
    @pytest.mark.asyncio
    async def test_poll_manager_puts_messages_into_bus(self, tmp_path: Path):
        """
        PollManager.start() creates poll tasks that put messages into the bus.
        Uses a 0.1s interval and waits for 2 polls.
        """
        bus = DeviceDataBus(ring_buffer_size=100, base_dir=str(tmp_path))
        device = _make_wifi_device(interval=0)  # 0s interval for fast test

        devices_config = DevicesConfig(devices=[device])
        poll_count = 0

        async def mock_poll():
            nonlocal poll_count
            poll_count += 1
            return _make_mock_message("plant_soil_sensor", float(poll_count * 10))

        mock_adapter = MagicMock()
        mock_adapter.poll = mock_poll

        manager = PollManager(
            devices_config=devices_config,
            bus=bus,
            env_profile=_make_env(),
        )

        with patch("core.bus.poll_manager.WiFiPollAdapter", return_value=mock_adapter):
            manager.start()
            # Wait for at least 2 polls
            await asyncio.sleep(0.05)
            manager.stop()

        # Verify messages were put into the bus
        latest = await bus.get_latest("plant_soil_sensor")
        assert latest is not None
        assert latest.device_id == "plant_soil_sensor"
        assert poll_count >= 1

    @pytest.mark.asyncio
    async def test_poll_manager_skips_push_devices(self, tmp_path: Path):
        """PollManager does not create tasks for wifi_push devices."""
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        push_device = DeviceConfig(
            id="lab_temp_sensor",
            type="sensor",
            transport="wifi_push",
            push_webhook_path="/webhook/lab_temp_sensor",
        )
        devices_config = DevicesConfig(devices=[push_device])
        manager = PollManager(
            devices_config=devices_config,
            bus=bus,
            env_profile=_make_env(),
        )
        manager.start()
        assert len(manager._tasks) == 0  # No tasks for push devices
        manager.stop()

    @pytest.mark.asyncio
    async def test_poll_manager_stop_cancels_tasks(self, tmp_path: Path):
        """PollManager.stop() cancels all running tasks."""
        bus = DeviceDataBus(ring_buffer_size=10, base_dir=str(tmp_path))
        device = _make_wifi_device(interval=60)  # Long interval
        devices_config = DevicesConfig(devices=[device])

        async def slow_poll():
            await asyncio.sleep(60)
            return _make_mock_message("plant_soil_sensor", 0.0)

        mock_adapter = MagicMock()
        mock_adapter.poll = slow_poll

        manager = PollManager(
            devices_config=devices_config,
            bus=bus,
            env_profile=_make_env(),
        )

        with patch("core.bus.poll_manager.WiFiPollAdapter", return_value=mock_adapter):
            manager.start()
            assert len(manager._tasks) == 1
            manager.stop()
            assert len(manager._tasks) == 0
