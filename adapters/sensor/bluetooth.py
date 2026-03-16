"""
Bluetooth sensor adapter using bleak (BLE GATT).
"""
from __future__ import annotations

import logging
import struct

from adapters.sensor.base import SensorAdapter
from core.config.models import DeviceConfig
from core.models.bus import BusMessage

logger = logging.getLogger(__name__)

# Default GATT characteristic UUID for custom sensor data
# Override via device_config.meta if needed
_DEFAULT_CHAR_UUID = "00002a6e-0000-1000-8000-00805f9b34fb"  # Temperature (standard)


class BluetoothAdapter(SensorAdapter):
    """
    Reads sensor data from a BLE device via GATT characteristic.

    Expects the characteristic to return a 4-byte IEEE 754 float (little-endian).
    """

    def __init__(self, device_config: DeviceConfig) -> None:
        super().__init__(device_config)
        # BLE device address should be in device_config.source
        if not device_config.source:
            raise ValueError(
                f"BluetoothAdapter requires source (BLE address) for device '{device_config.id}'"
            )
        self._address = device_config.source
        self._char_uuid = _DEFAULT_CHAR_UUID

    async def poll(self) -> BusMessage:
        try:
            from bleak import BleakClient  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "bleak is not installed. Install it with: pip install bleak"
            ) from exc

        try:
            async with BleakClient(self._address) as client:
                raw = await client.read_gatt_char(self._char_uuid)
                value = struct.unpack("<f", raw[:4])[0]
        except Exception as exc:
            raise RuntimeError(
                f"Bluetooth: Failed to read from '{self._address}': {exc}"
            ) from exc

        unit = self.device_config.subtype or "unknown"
        logger.debug("Bluetooth: %s = %s %s", self.device_config.id, value, unit)
        return self._make_message(value, unit)

    def is_available(self) -> bool:
        try:
            import bleak  # type: ignore[import]  # noqa: F401
            return True
        except ImportError:
            return False
