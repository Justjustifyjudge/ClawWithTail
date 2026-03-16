"""
Windows camera adapter using DirectShow backend via OpenCV.
"""
from __future__ import annotations

import logging

from adapters.camera.base import CameraAdapter
from core.config.models import DeviceConfig
from core.models.env_profile import EnvProfile

logger = logging.getLogger(__name__)


class DirectShowCameraAdapter(CameraAdapter):
    """Camera adapter for Windows using the DirectShow backend."""

    def __init__(self, device_config: DeviceConfig, env_profile: EnvProfile) -> None:
        super().__init__(device_config, env_profile)

    def capture_frame(self, save_path: str) -> str:
        import cv2  # type: ignore[import]
        # Use CAP_DSHOW for Windows DirectShow backend
        source = self._source if isinstance(self._source, int) else int(self._source)
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        try:
            if not cap.isOpened():
                raise RuntimeError(
                    f"DirectShow: Cannot open camera index {source} "
                    f"(device_id={self.device_config.id})"
                )
            ret, frame = cap.read()
            if not ret or frame is None:
                raise RuntimeError(
                    f"DirectShow: Failed to read frame from index {source}"
                )
            success = cv2.imwrite(save_path, frame)
            if not success:
                raise RuntimeError(f"DirectShow: Failed to write JPEG to '{save_path}'")
            logger.debug("DirectShow: Frame saved to %s", save_path)
            return save_path
        finally:
            cap.release()

    def is_available(self) -> bool:
        try:
            import cv2  # type: ignore[import]
            source = self._source if isinstance(self._source, int) else int(self._source)
            cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
            available = cap.isOpened()
            cap.release()
            return available
        except Exception:
            return False
