"""
adapters.sensor — factory function for sensor adapters.
"""
from __future__ import annotations

from adapters.sensor.base import SensorAdapter
from core.config.models import DeviceConfig
from core.models.env_profile import EnvProfile


def get_sensor_adapter(
    device_config: DeviceConfig,
    env_profile: EnvProfile | None = None,
) -> SensorAdapter:
    """
    Return the appropriate SensorAdapter based on device_config.transport.

    Supported transports:
        wifi_poll  → WiFiPollAdapter
        bluetooth  → BluetoothAdapter
        serial     → SerialAdapter
    """
    transport = device_config.transport

    if transport == "wifi_poll":
        from adapters.sensor.wifi_poll import WiFiPollAdapter
        return WiFiPollAdapter(device_config)
    elif transport == "bluetooth":
        from adapters.sensor.bluetooth import BluetoothAdapter
        return BluetoothAdapter(device_config)
    elif transport in ("serial", "usb"):
        from adapters.sensor.serial_adapter import SerialAdapter
        return SerialAdapter(device_config)
    else:
        raise ValueError(
            f"Unsupported sensor transport '{transport}' for device '{device_config.id}'. "
            f"Supported: wifi_poll, bluetooth, serial"
        )


__all__ = ["SensorAdapter", "get_sensor_adapter"]
