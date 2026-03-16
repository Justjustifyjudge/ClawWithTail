"""
Unit tests for camera adapters (T16 — Sprint 1 gate).
Uses mock cv2 to avoid requiring real hardware.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.config.models import DeviceConfig
from core.models.env_profile import EnvProfile


def _make_camera_device(source: str = "0") -> DeviceConfig:
    return DeviceConfig(id="test_cam", type="camera", transport="usb", source=source)


def _make_env(os: str = "linux", backend: str = "v4l2") -> EnvProfile:
    return EnvProfile(
        os=os, camera_backend=backend, gpu_available=False, gpu_type="none",
        bluetooth_available=False, python_version="3.11", yolo_variant="yolov8n",
    )


def _make_mock_cv2(frame_data=None):
    """Return a mock cv2 module with a working VideoCapture."""
    import numpy as np
    mock_cv2 = MagicMock()
    cap = MagicMock()
    cap.isOpened.return_value = True
    if frame_data is None:
        frame_data = np.zeros((480, 640, 3), dtype=np.uint8)
    cap.read.return_value = (True, frame_data)
    mock_cv2.VideoCapture.return_value = cap
    mock_cv2.imwrite.return_value = True
    mock_cv2.CAP_DSHOW = 700
    mock_cv2.CAP_AVFOUNDATION = 1200
    return mock_cv2


class TestV4L2CameraAdapter:
    def test_capture_frame_saves_file(self, tmp_path: Path):
        mock_cv2 = _make_mock_cv2()
        save_path = str(tmp_path / "frame.jpg")
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            from adapters.camera.v4l2 import V4L2CameraAdapter
            adapter = V4L2CameraAdapter(_make_camera_device(), _make_env("linux", "v4l2"))
            result = adapter.capture_frame(save_path)
        assert result == save_path
        mock_cv2.imwrite.assert_called_once_with(save_path, mock_cv2.VideoCapture().read()[1])

    def test_capture_frame_raises_when_camera_unavailable(self, tmp_path: Path):
        mock_cv2 = _make_mock_cv2()
        mock_cv2.VideoCapture.return_value.isOpened.return_value = False
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            from adapters.camera.v4l2 import V4L2CameraAdapter
            adapter = V4L2CameraAdapter(_make_camera_device(), _make_env())
            with pytest.raises(RuntimeError, match="Cannot open camera"):
                adapter.capture_frame(str(tmp_path / "frame.jpg"))

    def test_is_available_true(self):
        mock_cv2 = _make_mock_cv2()
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            from adapters.camera.v4l2 import V4L2CameraAdapter
            adapter = V4L2CameraAdapter(_make_camera_device(), _make_env())
            assert adapter.is_available() is True

    def test_is_available_false_when_not_opened(self):
        mock_cv2 = _make_mock_cv2()
        mock_cv2.VideoCapture.return_value.isOpened.return_value = False
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            from adapters.camera.v4l2 import V4L2CameraAdapter
            adapter = V4L2CameraAdapter(_make_camera_device(), _make_env())
            assert adapter.is_available() is False


class TestDirectShowCameraAdapter:
    def test_capture_frame_uses_cap_dshow(self, tmp_path: Path):
        mock_cv2 = _make_mock_cv2()
        save_path = str(tmp_path / "frame.jpg")
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            from adapters.camera.directshow import DirectShowCameraAdapter
            adapter = DirectShowCameraAdapter(
                _make_camera_device(), _make_env("windows", "directshow")
            )
            result = adapter.capture_frame(save_path)
        assert result == save_path
        # Verify CAP_DSHOW was used
        mock_cv2.VideoCapture.assert_called_with(0, mock_cv2.CAP_DSHOW)


class TestAVFoundationCameraAdapter:
    def test_capture_frame_uses_cap_avfoundation(self, tmp_path: Path):
        mock_cv2 = _make_mock_cv2()
        save_path = str(tmp_path / "frame.jpg")
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            from adapters.camera.avfoundation import AVFoundationCameraAdapter
            adapter = AVFoundationCameraAdapter(
                _make_camera_device(), _make_env("macos", "avfoundation")
            )
            result = adapter.capture_frame(save_path)
        assert result == save_path
        mock_cv2.VideoCapture.assert_called_with(0, mock_cv2.CAP_AVFOUNDATION)


class TestMockCameraAdapter:
    def test_capture_frame_writes_valid_jpeg(self, tmp_path: Path):
        from adapters.camera.mock import MockCameraAdapter
        adapter = MockCameraAdapter(_make_camera_device(), _make_env())
        save_path = str(tmp_path / "mock_frame.jpg")
        result = adapter.capture_frame(save_path)
        assert result == save_path
        assert Path(save_path).exists()
        assert Path(save_path).stat().st_size > 0
        # Verify JPEG magic bytes
        data = Path(save_path).read_bytes()
        assert data[:2] == b"\xFF\xD8"  # JPEG SOI marker

    def test_is_available_always_true(self):
        from adapters.camera.mock import MockCameraAdapter
        adapter = MockCameraAdapter(_make_camera_device(), _make_env())
        assert adapter.is_available() is True


class TestGetCameraAdapter:
    def test_linux_returns_v4l2(self):
        from adapters.camera import get_camera_adapter
        adapter = get_camera_adapter(_make_camera_device(), _make_env("linux", "v4l2"))
        assert type(adapter).__name__ == "V4L2CameraAdapter"

    def test_windows_returns_directshow(self):
        from adapters.camera import get_camera_adapter
        adapter = get_camera_adapter(
            _make_camera_device(), _make_env("windows", "directshow")
        )
        assert type(adapter).__name__ == "DirectShowCameraAdapter"

    def test_macos_returns_avfoundation(self):
        from adapters.camera import get_camera_adapter
        adapter = get_camera_adapter(
            _make_camera_device(), _make_env("macos", "avfoundation")
        )
        assert type(adapter).__name__ == "AVFoundationCameraAdapter"

    def test_no_camera_returns_mock(self):
        from adapters.camera import get_camera_adapter
        adapter = get_camera_adapter(_make_camera_device(), _make_env("linux", "none"))
        assert type(adapter).__name__ == "MockCameraAdapter"
