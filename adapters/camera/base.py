"""
Abstract base class for camera adapters.
Each platform (Linux/Windows/macOS) provides a concrete implementation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.config.models import DeviceConfig
from core.models.env_profile import EnvProfile


class CameraAdapter(ABC):
    """
    Platform-agnostic interface for capturing frames from a camera device.

    Design note: capture_frame saves the JPEG to disk and returns the path.
    Raw image bytes are NEVER passed through the bus or LLM context.
    """

    def __init__(self, device_config: DeviceConfig, env_profile: EnvProfile) -> None:
        self.device_config = device_config
        self.env_profile = env_profile
        # Resolve numeric source index or device path
        source = device_config.source or "0"
        try:
            self._source: int | str = int(source)
        except ValueError:
            self._source = source  # e.g. "/dev/video0"

    @abstractmethod
    def capture_frame(self, save_path: str) -> str:
        """
        Capture a single frame and save it as JPEG to save_path.

        Args:
            save_path: Absolute path where the JPEG should be saved.

        Returns:
            The actual path where the file was saved (may equal save_path).

        Raises:
            RuntimeError: if the camera is not available or capture fails.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the camera device can be opened successfully."""
