"""
Serial port sensor adapter using pyserial.
Reads line-delimited JSON from a serial port.
"""
from __future__ import annotations

import json
import logging

from adapters.sensor.base import SensorAdapter
from core.config.models import DeviceConfig
from core.models.bus import BusMessage

logger = logging.getLogger(__name__)


class SerialAdapter(SensorAdapter):
    """
    Reads sensor data from a serial port device.

    Expected line format (newline-terminated JSON):
        {"value": <float>, "unit": "<string>"}
    """

    def __init__(self, device_config: DeviceConfig) -> None:
        super().__init__(device_config)
        if not device_config.source:
            raise ValueError(
                f"SerialAdapter requires source (port path) for device '{device_config.id}'"
            )
        self._port = device_config.source
        self._baudrate = 9600  # default; can be extended via device_config meta

    async def poll(self) -> BusMessage:
        try:
            import serial  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is not installed. Install it with: pip install pyserial"
            ) from exc

        try:
            with serial.Serial(self._port, self._baudrate, timeout=5) as ser:
                line = ser.readline().decode("utf-8", errors="replace").strip()
        except Exception as exc:
            raise RuntimeError(
                f"Serial: Failed to read from '{self._port}': {exc}"
            ) from exc

        try:
            data = json.loads(line)
            value = float(data["value"])
            unit = str(data.get("unit", ""))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Serial: Invalid data from '{self._port}': {line!r}"
            ) from exc

        logger.debug("Serial: %s = %s %s", self.device_config.id, value, unit)
        return self._make_message(value, unit)

    def is_available(self) -> bool:
        try:
            import serial  # type: ignore[import]
            with serial.Serial(self._port, self._baudrate, timeout=1):
                return True
        except Exception:
            return False
