"""
Unit tests for sensor adapters (T16 — Sprint 1 gate).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config.models import DeviceConfig
from core.models.bus import BusMessage


def _make_wifi_device() -> DeviceConfig:
    return DeviceConfig(
        id="plant_soil_sensor",
        type="sensor",
        subtype="soil_moisture",
        transport="wifi_poll",
        poll_url="http://192.168.1.42/api/moisture",
        poll_interval_seconds=120,
    )


class TestWiFiPollAdapter:
    @pytest.mark.asyncio
    async def test_poll_returns_bus_message(self):
        """WiFiPollAdapter.poll() returns a valid BusMessage with correct fields."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": 42.5, "unit": "percent"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("adapters.sensor.wifi_poll.httpx.AsyncClient", return_value=mock_client):
            from adapters.sensor.wifi_poll import WiFiPollAdapter
            adapter = WiFiPollAdapter(_make_wifi_device())
            msg = await adapter.poll()

        assert isinstance(msg, BusMessage)
        assert msg.device_id == "plant_soil_sensor"
        assert msg.device_type == "sensor"
        assert msg.payload.type == "reading"
        assert msg.payload.data == 42.5
        assert msg.payload.unit == "percent"

    @pytest.mark.asyncio
    async def test_poll_raises_on_http_error(self):
        """WiFiPollAdapter.poll() raises RuntimeError on HTTP error."""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("adapters.sensor.wifi_poll.httpx.AsyncClient", return_value=mock_client):
            from adapters.sensor.wifi_poll import WiFiPollAdapter
            adapter = WiFiPollAdapter(_make_wifi_device())
            with pytest.raises(RuntimeError, match="HTTP error"):
                await adapter.poll()

    @pytest.mark.asyncio
    async def test_poll_raises_on_invalid_response(self):
        """WiFiPollAdapter.poll() raises RuntimeError when response is missing 'value'."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"temperature": 25.0}  # wrong key
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("adapters.sensor.wifi_poll.httpx.AsyncClient", return_value=mock_client):
            from adapters.sensor.wifi_poll import WiFiPollAdapter
            adapter = WiFiPollAdapter(_make_wifi_device())
            with pytest.raises(RuntimeError, match="Invalid response"):
                await adapter.poll()

    def test_requires_poll_url(self):
        """WiFiPollAdapter raises ValueError if poll_url is missing."""
        from adapters.sensor.wifi_poll import WiFiPollAdapter
        device = DeviceConfig(id="x", type="sensor", transport="wifi_poll")
        with pytest.raises(ValueError, match="poll_url"):
            WiFiPollAdapter(device)


class TestGetSensorAdapter:
    def test_wifi_poll_returns_wifi_adapter(self):
        from adapters.sensor import get_sensor_adapter
        adapter = get_sensor_adapter(_make_wifi_device())
        assert type(adapter).__name__ == "WiFiPollAdapter"

    def test_unsupported_transport_raises(self):
        from adapters.sensor import get_sensor_adapter
        device = DeviceConfig(id="x", type="sensor", transport="wifi_push")
        with pytest.raises(ValueError, match="Unsupported sensor transport"):
            get_sensor_adapter(device)
