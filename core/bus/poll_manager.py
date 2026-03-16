"""
Device Data Bus — Poll Manager (Poll path).

Manages asyncio tasks that periodically poll wifi_poll sensors
and put their readings into the Device Data Bus.

Camera devices (usb) are NOT polled here — they are captured on-demand
by the vision MCP Tool.

WiFi push devices are NOT polled here — they push to the Webhook Server.
"""
from __future__ import annotations

import asyncio
import logging

from core.config.models import DevicesConfig
from core.models.env_profile import EnvProfile

logger = logging.getLogger(__name__)


class PollManager:
    def __init__(
        self,
        devices_config: DevicesConfig,
        bus,  # DeviceDataBus — avoid circular import
        env_profile: EnvProfile,
    ) -> None:
        self._devices_config = devices_config
        self._bus = bus
        self._env_profile = env_profile
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        """
        Start a poll loop for every wifi_poll device in devices_config.
        Safe to call multiple times — existing tasks are cancelled first.
        """
        self.stop()
        for device in self._devices_config.devices:
            if device.transport == "wifi_poll":
                task = asyncio.create_task(
                    self._poll_loop(device),
                    name=f"poll_{device.id}",
                )
                self._tasks.append(task)
                logger.info(
                    "PollManager: started poll loop for %s (interval=%ds)",
                    device.id,
                    device.poll_interval_seconds or 60,
                )

    def stop(self) -> None:
        """Cancel all running poll tasks."""
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()
        logger.info("PollManager: all poll tasks stopped")

    async def _poll_loop(self, device_config) -> None:
        """Infinite poll loop for a single wifi_poll device."""
        from adapters.sensor.wifi_poll import WiFiPollAdapter

        adapter = WiFiPollAdapter(device_config)
        interval = device_config.poll_interval_seconds or 60

        while True:
            try:
                msg = await adapter.poll()
                await self._bus.put(msg)
                logger.debug(
                    "PollManager: polled %s → %s %s",
                    device_config.id,
                    msg.payload.data,
                    msg.payload.unit,
                )
            except asyncio.CancelledError:
                logger.info("PollManager: poll loop for %s cancelled", device_config.id)
                return
            except Exception as exc:
                logger.warning(
                    "PollManager: poll error for %s: %s (retrying in %ds)",
                    device_config.id,
                    exc,
                    interval,
                )
            await asyncio.sleep(interval)
