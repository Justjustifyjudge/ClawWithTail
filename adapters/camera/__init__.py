"""
adapters.camera — factory function for camera adapters.
"""
from __future__ import annotations

from adapters.camera.base import CameraAdapter
from core.config.models import DeviceConfig
from core.models.env_profile import EnvProfile


def get_camera_adapter(
    device_config: DeviceConfig,
    env_profile: EnvProfile,
) -> CameraAdapter:
    """
    Return the appropriate CameraAdapter for the current environment.

    Selection logic:
        linux   → V4L2CameraAdapter
        windows → DirectShowCameraAdapter
        macos   → AVFoundationCameraAdapter
        none    → MockCameraAdapter
    """
    backend = env_profile.camera_backend

    if backend == "v4l2":
        from adapters.camera.v4l2 import V4L2CameraAdapter
        return V4L2CameraAdapter(device_config, env_profile)
    elif backend == "directshow":
        from adapters.camera.directshow import DirectShowCameraAdapter
        return DirectShowCameraAdapter(device_config, env_profile)
    elif backend == "avfoundation":
        from adapters.camera.avfoundation import AVFoundationCameraAdapter
        return AVFoundationCameraAdapter(device_config, env_profile)
    else:
        from adapters.camera.mock import MockCameraAdapter
        return MockCameraAdapter(device_config, env_profile)


__all__ = ["CameraAdapter", "get_camera_adapter"]
