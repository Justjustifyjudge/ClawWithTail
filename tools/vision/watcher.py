"""
tools.vision.watcher — Background frame monitoring loop (T19).

The _watch_loop coroutine runs as an asyncio.Task inside the vision MCP server.
It captures frames at regular intervals, runs object detection, and logs
detection events to a JSONL file.

Detection logic:
  - Every interval_seconds: capture a frame and run detect_objects
  - If any target label is detected: write event to JSONL, sleep cooldown_seconds
  - If no target label: sleep interval_seconds
  - On asyncio.CancelledError: exit cleanly
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

# Module-level imports for mockability in tests
from tools.vision.server import _capture_frame, _detect_objects

logger = logging.getLogger(__name__)


async def _watch_loop(
    source_id: str,
    labels: list[str],
    interval_seconds: int,
    cooldown_seconds: int,
    event_log_path: str,
) -> None:
    """
    Background monitoring loop.

    Args:
        source_id: Camera device ID to capture from.
        labels: List of YOLO labels to watch for (e.g. ["cup", "bottle"]).
        interval_seconds: How often to capture a frame (seconds).
        cooldown_seconds: How long to sleep after a detection event (seconds).
        event_log_path: Path to the JSONL file where events are written.
    """
    log_path = Path(event_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    label_set = set(labels)

    logger.info(
        "watcher: started for source=%s labels=%s interval=%ds cooldown=%ds log=%s",
        source_id, labels, interval_seconds, cooldown_seconds, event_log_path,
    )

    while True:
        try:
            # 1. Capture frame
            capture_result = await _capture_frame(source_id, save_path=None)
            frame_path = capture_result["frame_path"]

            # 2. Detect objects
            detections = await _detect_objects(frame_path, confidence=0.5)

            # 3. Check if any target label was detected
            detected_labels = [d["label"] for d in detections if d["label"] in label_set]
            detected_confidences = [
                d["confidence"] for d in detections if d["label"] in label_set
            ]

            if detected_labels:
                # Write event to JSONL
                event = {
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "labels": detected_labels,
                    "confidences": detected_confidences,
                    "frame_path": frame_path,
                }
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")

                logger.info(
                    "watcher: detected %s in %s, sleeping %ds (cooldown)",
                    detected_labels, source_id, cooldown_seconds,
                )
                await asyncio.sleep(cooldown_seconds)
            else:
                logger.debug(
                    "watcher: no target labels in %s, sleeping %ds",
                    source_id, interval_seconds,
                )
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("watcher: loop for source=%s cancelled, exiting", source_id)
            return
        except Exception as exc:
            logger.warning(
                "watcher: error in loop for source=%s: %s (retrying in %ds)",
                source_id, exc, interval_seconds,
            )
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                return
