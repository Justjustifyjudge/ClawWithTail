"""
Unit tests for environment detector (T09 — Sprint 0 gate).
Uses unittest.mock.patch to simulate different OS/GPU/camera environments.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from env.detector import detect
from env.state import get_env_profile, reset_env_profile


class TestDetectOS:
    def test_linux(self):
        with patch("platform.system", return_value="Linux"):
            profile = detect()
        assert profile.os == "linux"

    def test_windows(self):
        with patch("platform.system", return_value="Windows"):
            profile = detect()
        assert profile.os == "windows"

    def test_macos(self):
        with patch("platform.system", return_value="Darwin"):
            profile = detect()
        assert profile.os == "macos"


class TestDetectGPU:
    def test_cuda_available(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch("platform.system", return_value="Linux"), \
             patch.dict("sys.modules", {"torch": mock_torch}):
            profile = detect()
        assert profile.gpu_type == "cuda"
        assert profile.gpu_available is True
        assert profile.yolo_variant == "yolov8s"

    def test_mps_available(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.backends.mps.is_available.return_value = True
        with patch("platform.system", return_value="Darwin"), \
             patch.dict("sys.modules", {"torch": mock_torch}):
            profile = detect()
        assert profile.gpu_type == "mps"
        assert profile.yolo_variant == "yolov8s"

    def test_no_gpu(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.backends.mps.is_available.return_value = False
        with patch("platform.system", return_value="Linux"), \
             patch.dict("sys.modules", {"torch": mock_torch}):
            profile = detect()
        assert profile.gpu_type == "none"
        assert profile.gpu_available is False
        assert profile.yolo_variant == "yolov8n"

    def test_torch_not_installed(self):
        """When torch is not installed, GPU defaults to 'none' without crashing."""
        with patch("platform.system", return_value="Linux"), \
             patch.dict("sys.modules", {"torch": None}):
            profile = detect()
        assert profile.gpu_type == "none"


class TestDetectCamera:
    def test_camera_unavailable_does_not_crash(self):
        """When cv2.VideoCapture raises, camera_backend is 'none' and no exception is raised."""
        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.side_effect = Exception("no camera")
        with patch("platform.system", return_value="Linux"), \
             patch.dict("sys.modules", {"cv2": mock_cv2}):
            profile = detect()
        assert profile.camera_backend == "none"

    def test_linux_camera_backend(self):
        mock_cv2 = MagicMock()
        cap_mock = MagicMock()
        cap_mock.isOpened.return_value = True
        mock_cv2.VideoCapture.return_value = cap_mock
        with patch("platform.system", return_value="Linux"), \
             patch.dict("sys.modules", {"cv2": mock_cv2}):
            profile = detect()
        assert profile.camera_backend == "v4l2"

    def test_windows_camera_backend(self):
        mock_cv2 = MagicMock()
        cap_mock = MagicMock()
        cap_mock.isOpened.return_value = True
        mock_cv2.VideoCapture.return_value = cap_mock
        with patch("platform.system", return_value="Windows"), \
             patch.dict("sys.modules", {"cv2": mock_cv2}):
            profile = detect()
        assert profile.camera_backend == "directshow"


class TestEnvProfileSingleton:
    def test_singleton_caches_result(self):
        reset_env_profile()
        p1 = get_env_profile()
        p2 = get_env_profile()
        assert p1 is p2

    def test_reset_forces_redetection(self):
        reset_env_profile()
        p1 = get_env_profile()
        reset_env_profile()
        p2 = get_env_profile()
        # Both should be valid EnvProfile instances (content may differ if env changed)
        assert p1.os == p2.os  # OS doesn't change between calls
