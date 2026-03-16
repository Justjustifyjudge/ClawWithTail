"""
EnvProfile — output of the environment detector (M-ENV).
Describes the host machine's capabilities relevant to ClawWithTail.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class EnvProfile:
    os: Literal["linux", "windows", "macos"]
    camera_backend: Literal["v4l2", "directshow", "avfoundation", "none"]
    gpu_available: bool
    gpu_type: Literal["cuda", "mps", "none"]
    bluetooth_available: bool
    python_version: str
    # [{"id": "0", "name": "USB Camera"}, ...]
    detected_cameras: list[dict] = field(default_factory=list)
    # ["/dev/ttyUSB0", "COM3", ...]
    detected_serial_ports: list[str] = field(default_factory=list)
    # Resolved by detector based on gpu_type; can be overridden via config
    yolo_variant: Literal["yolov8n", "yolov8s"] = "yolov8n"
