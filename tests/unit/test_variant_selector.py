"""
Unit tests for variant selector (T09 — Sprint 0 gate).
Covers all OS × GPU combinations per spec.md §9.2.
"""
from __future__ import annotations

import pytest

from core.models.env_profile import EnvProfile
from env.variant_selector import select_camera_adapter, select_yolo_variant


def _make_profile(os: str, gpu_type: str, camera_backend: str, yolo_variant: str) -> EnvProfile:
    return EnvProfile(
        os=os,
        camera_backend=camera_backend,
        gpu_available=(gpu_type != "none"),
        gpu_type=gpu_type,
        bluetooth_available=False,
        python_version="3.11.0",
        yolo_variant=yolo_variant,
    )


class TestSelectCameraAdapter:
    def test_linux_v4l2(self):
        profile = _make_profile("linux", "none", "v4l2", "yolov8n")
        assert select_camera_adapter(profile) == "V4L2CameraAdapter"

    def test_windows_directshow(self):
        profile = _make_profile("windows", "none", "directshow", "yolov8n")
        assert select_camera_adapter(profile) == "DirectShowCameraAdapter"

    def test_macos_avfoundation(self):
        profile = _make_profile("macos", "none", "avfoundation", "yolov8n")
        assert select_camera_adapter(profile) == "AVFoundationCameraAdapter"

    def test_no_camera_returns_mock(self):
        profile = _make_profile("linux", "none", "none", "yolov8n")
        assert select_camera_adapter(profile) == "MockCameraAdapter"


class TestSelectYoloVariant:
    def test_cpu_returns_nano(self):
        profile = _make_profile("linux", "none", "v4l2", "yolov8n")
        assert select_yolo_variant(profile) == "yolov8n"

    def test_cuda_returns_small(self):
        profile = _make_profile("linux", "cuda", "v4l2", "yolov8s")
        assert select_yolo_variant(profile) == "yolov8s"

    def test_mps_returns_small(self):
        profile = _make_profile("macos", "mps", "avfoundation", "yolov8s")
        assert select_yolo_variant(profile) == "yolov8s"

    def test_windows_cpu_returns_nano(self):
        profile = _make_profile("windows", "none", "directshow", "yolov8n")
        assert select_yolo_variant(profile) == "yolov8n"

    def test_linux_cuda_returns_small(self):
        profile = _make_profile("linux", "cuda", "v4l2", "yolov8s")
        assert select_yolo_variant(profile) == "yolov8s"

    def test_macos_cpu_returns_nano(self):
        profile = _make_profile("macos", "none", "avfoundation", "yolov8n")
        assert select_yolo_variant(profile) == "yolov8n"
