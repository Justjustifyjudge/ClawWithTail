"""
Unit tests for Webhook Server (T16 — Sprint 1 gate).
Uses FastAPI TestClient to test the HTTP endpoints.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.bus.webhook_server import app


class TestWebhookServer:
    def test_valid_device_returns_200(self):
        """POST to a registered device_id returns 200 with status ok."""
        import core.bus.webhook_server as ws
        mock_devices_config = MagicMock()
        mock_devices_config.devices = [MagicMock(id="lab_temp_sensor")]
        mock_bus = MagicMock()
        mock_bus.put = AsyncMock()

        with patch.object(ws, "devices_config", mock_devices_config), \
             patch.object(ws, "_get_bus", return_value=mock_bus):
            client = TestClient(app)
            response = client.post(
                "/webhook/lab_temp_sensor",
                json={"value": 25.3, "unit": "celsius"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_unregistered_device_returns_404(self):
        """POST to an unregistered device_id returns 404."""
        import core.bus.webhook_server as ws
        mock_devices_config = MagicMock()
        mock_devices_config.devices = [MagicMock(id="lab_temp_sensor")]
        mock_bus = MagicMock()
        mock_bus.put = AsyncMock()

        with patch.object(ws, "devices_config", mock_devices_config), \
             patch.object(ws, "_get_bus", return_value=mock_bus):
            client = TestClient(app)
            response = client.post(
                "/webhook/unknown_device",
                json={"value": 25.3, "unit": "celsius"},
            )

        assert response.status_code == 404

    def test_health_endpoint(self):
        """GET /health returns 200."""
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_message_put_into_bus(self):
        """Webhook handler calls bus.put() with correct BusMessage."""
        import core.bus.webhook_server as ws
        from core.models.bus import BusMessage

        mock_devices_config = MagicMock()
        mock_devices_config.devices = [MagicMock(id="plant_soil_sensor")]
        mock_bus = MagicMock()
        mock_bus.put = AsyncMock()

        with patch.object(ws, "devices_config", mock_devices_config), \
             patch.object(ws, "_get_bus", return_value=mock_bus):
            client = TestClient(app)
            client.post(
                "/webhook/plant_soil_sensor",
                json={"value": 42.0, "unit": "percent"},
            )

        mock_bus.put.assert_called_once()
        call_args = mock_bus.put.call_args[0][0]
        assert isinstance(call_args, BusMessage)
        assert call_args.device_id == "plant_soil_sensor"
        assert call_args.payload.data == 42.0
        assert call_args.payload.unit == "percent"
