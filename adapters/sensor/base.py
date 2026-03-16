"""
Abstract base class for sensor adapters.
Supports WiFi poll, Bluetooth, and serial transport.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from core.config.models import DeviceConfig
from core.models.bus import BusMessage, BusPayload


class SensorAdapter(ABC):
    """
    Platform-agnostic interface for reading data from a sensor device.
    """

    def __init__(self, device_config: DeviceConfig) -> None:
        self.device_config = device_config

    @abstractmethod
    async def poll(self) -> BusMessage:
        """
        Read one sample from the sensor and return it as a BusMessage.

        Returns:
            BusMessage with device_type="sensor" and payload.type="reading".

        Raises:
            RuntimeError: if the sensor is unreachable or returns invalid data.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the sensor device is reachable."""

    def _make_message(self, value: float, unit: str, meta: dict | None = None) -> BusMessage:
        """Helper: construct a BusMessage from a sensor reading."""
        return BusMessage(
            device_id=self.device_config.id,
            device_type="sensor",
            timestamp=datetime.now(tz=timezone.utc),
            payload=BusPayload(
                type="reading",
                data=value,
                unit=unit,
                meta=meta or {},
            ),
        )
