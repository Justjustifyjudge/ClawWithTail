"""
tools.vision.camera_registry — Initializes camera adapters at server startup.

Reads devices_config and env_profile to build a map of
device_id → CameraAdapter, so vision tools can look up adapters by ID.
"""
from __future__ import annotations

import logging

from adapters.camera import get_camera_adapter
from adapters.camera.base import CameraAdapter
from core.config import devices_config
from env.state import get_env_profile

logger = logging.getLogger(__name__)


class CameraRegistry:
    """
    Registry of CameraAdapter instances, keyed by device_id.
    Initialized once at server startup.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, CameraAdapter] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Build the adapter map from devices_config and env_profile."""
        if self._initialized:
            return
        profile = get_env_profile()
        for device in devices_config.devices:
            if device.type == "camera":
                adapter = get_camera_adapter(device, profile)
                self._adapters[device.id] = adapter
                logger.info(
                    "CameraRegistry: registered '%s' → %s (available=%s)",
                    device.id,
                    type(adapter).__name__,
                    adapter.is_available(),
                )
        self._initialized = True

    def get(self, device_id: str) -> CameraAdapter:
        """
        Return the CameraAdapter for the given device_id.

        Raises:
            KeyError: if device_id is not registered.
        """
        if not self._initialized:
            self.initialize()
        if device_id not in self._adapters:
            raise KeyError(
                f"CameraRegistry: device '{device_id}' not found. "
                f"Registered: {list(self._adapters.keys())}"
            )
        return self._adapters[device_id]

    def list_ids(self) -> list[str]:
        """Return all registered camera device IDs."""
        if not self._initialized:
            self.initialize()
        return list(self._adapters.keys())


# Module-level singleton — shared across all vision tool handlers
camera_registry = CameraRegistry()
