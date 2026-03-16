"""
Integration test: Camera capture pipeline (T16 — Sprint 1 gate).
Uses mock cv2 to avoid requiring real hardware.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.config.models import DeviceConfig
from core.models.env_profile import EnvProfile


def _make_mock_cv2():
    import numpy as np
    mock_cv2 = MagicMock()
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
    mock_cv2.VideoCapture.return_value = cap
    mock_cv2.imwrite.side_effect = lambda path, frame: (
        Path(path).parent.mkdir(parents=True, exist_ok=True) or
        Path(path).write_bytes(b"\xFF\xD8\xFF\xD9") or True
    )
    return mock_cv2


class TestCameraCapturePipeline:
    def test_v4l2_capture_creates_file(self, tmp_path: Path):
        """V4L2CameraAdapter.capture_frame() creates a file at the given path."""
        mock_cv2 = _make_mock_cv2()
        device = DeviceConfig(id="desk_camera", type="camera", transport="usb", source="0")
        profile = EnvProfile(
            os="linux", camera_backend="v4l2", gpu_available=False,
            gpu_type="none", bluetooth_available=False, python_version="3.11",
            yolo_variant="yolov8n",
        )
        save_path = str(tmp_path / "frame.jpg")

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            from adapters.camera.v4l2 import V4L2CameraAdapter
            adapter = V4L2CameraAdapter(device, profile)
            result = adapter.capture_frame(save_path)

        assert result == save_path
        mock_cv2.imwrite.assert_called_once()

    def test_mock_adapter_creates_valid_jpeg(self, tmp_path: Path):
        """MockCameraAdapter creates a valid JPEG file (no cv2 needed)."""
        from adapters.camera.mock import MockCameraAdapter
        device = DeviceConfig(id="desk_camera", type="camera", transport="usb", source="0")
        profile = EnvProfile(
            os="linux", camera_backend="none", gpu_available=False,
            gpu_type="none", bluetooth_available=False, python_version="3.11",
            yolo_variant="yolov8n",
        )
        save_path = str(tmp_path / "mock_frame.jpg")
        adapter = MockCameraAdapter(device, profile)
        result = adapter.capture_frame(save_path)

        assert Path(result).exists()
        assert Path(result).stat().st_size > 0
        # JPEG magic bytes
        assert Path(result).read_bytes()[:2] == b"\xFF\xD8"
