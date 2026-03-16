"""
Linux camera adapter using V4L2 backend via OpenCV.
"""
from __future__ import annotations

import logging

from adapters.camera.base import CameraAdapter
from core.config.models import DeviceConfig
from core.models.env_profile import EnvProfile

logger = logging.getLogger(__name__)


class V4L2CameraAdapter(CameraAdapter):
    """Camera adapter for Linux using the V4L2 backend."""

    def __init__(self, device_config: DeviceConfig, env_profile: EnvProfile) -> None:
        super().__init__(device_config, env_profile)

    def capture_frame(self, save_path: str) -> str:
        import cv2  # type: ignore[import]
        cap = cv2.VideoCapture(self._source)
        try:
            if not cap.isOpened():
                raise RuntimeError(
                    f"V4L2: Cannot open camera source '{self._source}' "
                    f"(device_id={self.device_config.id})"
                )
            ret, frame = cap.read()
            if not ret or frame is None:
                raise RuntimeError(
                    f"V4L2: Failed to read frame from source '{self._source}'"
                )
            success = cv2.imwrite(save_path, frame)
            if not success:
                raise RuntimeError(f"V4L2: Failed to write JPEG to '{save_path}'")
            logger.debug("V4L2: Frame saved to %s", save_path)
            return save_path
        finally:
            cap.release()

    def is_available(self) -> bool:
        try:
            import cv2  # type: ignore[import]
            cap = cv2.VideoCapture(self._source)
            available = cap.isOpened()
            cap.release()
            return available
        except Exception:
            return False
