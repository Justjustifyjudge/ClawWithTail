"""
WiFi Poll sensor adapter — polls a sensor's HTTP endpoint periodically.
"""
from __future__ import annotations

import logging

import httpx

from adapters.sensor.base import SensorAdapter
from core.config.models import DeviceConfig
from core.models.bus import BusMessage

logger = logging.getLogger(__name__)


class WiFiPollAdapter(SensorAdapter):
    """
    Polls a sensor device over WiFi via HTTP GET.

    Expected response format:
        {"value": <float>, "unit": "<string>"}
    """

    def __init__(self, device_config: DeviceConfig) -> None:
        super().__init__(device_config)
        if not device_config.poll_url:
            raise ValueError(
                f"WiFiPollAdapter requires poll_url for device '{device_config.id}'"
            )
        self._url = device_config.poll_url

    async def poll(self) -> BusMessage:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._url)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"WiFiPoll: HTTP error polling '{self._url}': {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"WiFiPoll: Failed to poll '{self._url}': {exc}"
            ) from exc

        try:
            value = float(data["value"])
            unit = str(data.get("unit", ""))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"WiFiPoll: Invalid response from '{self._url}': {data!r}"
            ) from exc

        logger.debug(
            "WiFiPoll: %s = %s %s", self.device_config.id, value, unit
        )
        return self._make_message(value, unit)

    def is_available(self) -> bool:
        try:
            response = httpx.get(self._url, timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
