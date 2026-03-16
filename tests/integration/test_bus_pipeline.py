"""
Integration test: Bus pipeline end-to-end (T16 — Sprint 1 gate).
Tests the full path: Webhook POST → Bus → JSONL file.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.bus.bus import DeviceDataBus
from core.bus.webhook_server import app


@pytest.fixture
def tmp_bus(tmp_path):
    """Create a fresh DeviceDataBus backed by tmp_path."""
    return DeviceDataBus(ring_buffer_size=100, base_dir=str(tmp_path))


class TestBusPipeline:
    def test_webhook_to_bus_to_jsonl(self, tmp_path: Path):
        """
        Full pipeline: POST to webhook → message in bus → JSONL file written.
        """
        import core.bus.webhook_server as ws
        bus = DeviceDataBus(ring_buffer_size=100, base_dir=str(tmp_path))

        mock_devices_config = MagicMock()
        mock_devices_config.devices = [MagicMock(id="plant_soil_sensor")]

        with patch.object(ws, "devices_config", mock_devices_config), \
             patch.object(ws, "_get_bus", return_value=bus):
            client = TestClient(app)
            response = client.post(
                "/webhook/plant_soil_sensor",
                json={"value": 35.7, "unit": "percent"},
            )

        assert response.status_code == 200

        # Verify JSONL file was written
        log_file = tmp_path / "data" / "sensor_logs" / "plant_soil_sensor.jsonl"
        assert log_file.exists(), "JSONL log file should be created after webhook POST"

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["device_id"] == "plant_soil_sensor"
        assert record["payload"]["data"] == 35.7
        assert record["payload"]["unit"] == "percent"

    def test_multiple_posts_append_to_jsonl(self, tmp_path: Path):
        """Multiple webhook POSTs append multiple lines to the JSONL file."""
        import core.bus.webhook_server as ws
        bus = DeviceDataBus(ring_buffer_size=100, base_dir=str(tmp_path))
        mock_devices_config = MagicMock()
        mock_devices_config.devices = [MagicMock(id="lab_temp_sensor")]

        with patch.object(ws, "devices_config", mock_devices_config), \
             patch.object(ws, "_get_bus", return_value=bus):
            client = TestClient(app)
            for value in [20.0, 21.5, 23.0]:
                client.post(
                    "/webhook/lab_temp_sensor",
                    json={"value": value, "unit": "celsius"},
                )

        log_file = tmp_path / "data" / "sensor_logs" / "lab_temp_sensor.jsonl"
        lines = [l for l in log_file.read_text(encoding="utf-8").strip().split("\n") if l]
        assert len(lines) == 3
