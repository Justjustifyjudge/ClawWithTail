"""
Device Data Bus — the central data hub of ClawWithTail.

All device data (camera frames, sensor readings) flows through this bus.
MCP Tools read from the bus; they never talk to devices directly.

Design:
  - Per-device asyncio.Queue acts as a ring buffer (bounded size)
  - Every message is also appended to a JSONL file for persistence
  - get_latest() peeks without consuming (non-destructive read)
  - get_history() reads from JSONL for time-range queries
  - get_stats() computes min/max/avg/trend over a time window
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.models.bus import BusMessage

logger = logging.getLogger(__name__)


class DeviceDataBus:
    def __init__(self, ring_buffer_size: int = 1000, base_dir: str = "~/.clawtail") -> None:
        self._ring_buffer_size = ring_buffer_size
        self._base_dir = Path(base_dir).expanduser().resolve()
        self._log_dir = self._base_dir / "data" / "sensor_logs"
        # Per-device queues (created on first use)
        self._queues: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_queue(self, device_id: str) -> asyncio.Queue:
        if device_id not in self._queues:
            self._queues[device_id] = asyncio.Queue(maxsize=self._ring_buffer_size)
        return self._queues[device_id]

    def _log_path(self, device_id: str) -> Path:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        return self._log_dir / f"{device_id}.jsonl"

    def _append_jsonl(self, msg: BusMessage) -> None:
        """Append a BusMessage to the device's JSONL log file (sync, fast)."""
        try:
            with open(self._log_path(msg.device_id), "a", encoding="utf-8") as f:
                f.write(msg.to_jsonl() + "\n")
        except OSError as exc:
            logger.warning("Failed to persist BusMessage for %s: %s", msg.device_id, exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def put(self, msg: BusMessage) -> None:
        """
        Put a message into the ring buffer for its device.
        If the buffer is full, the oldest message is silently dropped.
        Also appends to the JSONL persistence file.
        """
        async with self._lock:
            q = self._get_queue(msg.device_id)
            if q.full():
                try:
                    q.get_nowait()  # drop oldest
                except asyncio.QueueEmpty:
                    pass
            await q.put(msg)
        # Persist outside the lock (I/O should not block bus operations)
        self._append_jsonl(msg)

    async def get_latest(self, device_id: str) -> BusMessage | None:
        """
        Return the most recently received message for a device without consuming it.
        Returns None if no messages have been received yet.
        """
        async with self._lock:
            q = self._get_queue(device_id)
            if q.empty():
                return None
            # Drain queue to list, peek last, refill
            items: list[BusMessage] = []
            while not q.empty():
                try:
                    items.append(q.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for item in items:
                await q.put(item)
            return items[-1] if items else None

    def get_history(
        self,
        device_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[BusMessage]:
        """
        Read messages from the JSONL log within [from_iso, to_iso] (inclusive).
        Both timestamps must be ISO 8601 strings.
        """
        log_path = self._log_path(device_id)
        if not log_path.exists():
            return []

        from_dt = datetime.fromisoformat(from_iso)
        to_dt = datetime.fromisoformat(to_iso)

        # Make both timezone-aware (UTC) if naive
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=timezone.utc)
        if to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=timezone.utc)

        results: list[BusMessage] = []
        try:
            with open(log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = BusMessage.from_jsonl(line)
                        ts = msg.timestamp
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if from_dt <= ts <= to_dt:
                            results.append(msg)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except OSError:
            pass
        return results

    def get_stats(self, device_id: str, window_minutes: int = 60) -> dict:
        """
        Compute statistics for sensor readings in the last window_minutes.

        Returns:
            {
                "device_id": str,
                "window_minutes": int,
                "count": int,
                "min": float | None,
                "max": float | None,
                "avg": float | None,
                "trend": "rising" | "falling" | "stable" | "insufficient_data",
                "unit": str | None,
            }
        """
        now = datetime.now(tz=timezone.utc)
        from_dt = now - timedelta(minutes=window_minutes)
        messages = self.get_history(
            device_id,
            from_iso=from_dt.isoformat(),
            to_iso=now.isoformat(),
        )
        # Filter to numeric readings only
        readings = [
            float(m.payload.data)
            for m in messages
            if m.payload.type == "reading" and isinstance(m.payload.data, (int, float))
        ]
        unit = next(
            (m.payload.unit for m in messages if m.payload.type == "reading"),
            None,
        )

        if not readings:
            return {
                "device_id": device_id,
                "window_minutes": window_minutes,
                "count": 0,
                "min": None,
                "max": None,
                "avg": None,
                "trend": "insufficient_data",
                "unit": unit,
            }

        avg = sum(readings) / len(readings)
        trend = "insufficient_data"
        if len(readings) >= 3:
            first_half = readings[: len(readings) // 2]
            second_half = readings[len(readings) // 2 :]
            first_avg = sum(first_half) / len(first_half)
            second_avg = sum(second_half) / len(second_half)
            diff = second_avg - first_avg
            if diff > 0.5:
                trend = "rising"
            elif diff < -0.5:
                trend = "falling"
            else:
                trend = "stable"

        return {
            "device_id": device_id,
            "window_minutes": window_minutes,
            "count": len(readings),
            "min": min(readings),
            "max": max(readings),
            "avg": round(avg, 3),
            "trend": trend,
            "unit": unit,
        }
