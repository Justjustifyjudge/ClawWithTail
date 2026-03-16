"""
BusMessage — canonical data unit flowing through the Device Data Bus.

Design note: Camera frames are NEVER passed as base64 through the bus.
The adapter saves the JPEG to ~/.clawtail/data/frames/ and puts the
file path in payload.data. This keeps bus messages small.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class BusPayload:
    type: Literal["frame", "reading"]
    # For frame: local file path (JPEG saved by adapter)
    # For reading: numeric value as float
    data: str | float
    unit: str | None = None   # e.g. "celsius", "percent"; None for frames
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "unit": self.unit,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BusPayload":
        return cls(
            type=d["type"],
            data=d["data"],
            unit=d.get("unit"),
            meta=d.get("meta", {}),
        )


@dataclass
class BusMessage:
    device_id: str
    device_type: Literal["camera", "sensor"]
    timestamp: datetime
    payload: BusPayload

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload.to_dict(),
        }

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line (no trailing newline)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "BusMessage":
        return cls(
            device_id=d["device_id"],
            device_type=d["device_type"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            payload=BusPayload.from_dict(d["payload"]),
        )

    @classmethod
    def from_jsonl(cls, line: str) -> "BusMessage":
        return cls.from_dict(json.loads(line))
