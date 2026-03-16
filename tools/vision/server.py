"""
tools.vision.server — vision MCP Tool Package.

Provides tools for camera capture, object detection, image analysis,
frame comparison, object counting, and background watch monitoring.

Tools:
  vision.capture_frame    — capture a JPEG frame from a camera
  vision.detect_objects   — run YOLOv8 object detection on a frame
  vision.analyze_image    — analyze an image with a vision LLM
  vision.compare_frames   — compare two frames and describe differences
  vision.count_objects    — count events from a watcher event log
  vision.start_watch      — start a background frame-monitoring loop
  vision.stop_watch       — stop a background monitoring loop
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

from tools.vision.camera_registry import camera_registry
from core.storage_init import init_storage

logger = logging.getLogger(__name__)

app = Server("vision-tools")


# ── Tool definitions ──────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="vision.capture_frame",
            description="Capture a single JPEG frame from a registered camera device and save it to disk.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Camera device ID (e.g. 'desk_camera')",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Optional absolute path to save the JPEG. Auto-generated if omitted.",
                    },
                },
                "required": ["source_id"],
            },
        ),
        Tool(
            name="vision.detect_objects",
            description="Run YOLOv8 object detection on a saved frame. Returns a list of detected objects.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frame_path": {
                        "type": "string",
                        "description": "Absolute path to the JPEG frame file.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Minimum confidence threshold (0.0–1.0). Default: 0.5",
                        "default": 0.5,
                    },
                },
                "required": ["frame_path"],
            },
        ),
        Tool(
            name="vision.analyze_image",
            description=(
                "Analyze an image using a vision LLM. "
                "Returns a text description. The base64 image data is NOT included in the response."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "frame_path": {
                        "type": "string",
                        "description": "Absolute path to the JPEG frame file.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Analysis prompt (e.g. 'Describe the health of this plant')",
                    },
                },
                "required": ["frame_path", "prompt"],
            },
        ),
        Tool(
            name="vision.compare_frames",
            description="Compare two frames and describe the differences using a vision LLM.",
            inputSchema={
                "type": "object",
                "properties": {
                    "frame_path_a": {"type": "string"},
                    "frame_path_b": {"type": "string"},
                    "prompt": {
                        "type": "string",
                        "description": "Optional custom prompt. Default: describe differences.",
                    },
                },
                "required": ["frame_path_a", "frame_path_b"],
            },
        ),
        Tool(
            name="vision.count_objects",
            description="Count detection events from a watcher event log within a time window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_log_path": {
                        "type": "string",
                        "description": "Absolute path to the JSONL event log file.",
                    },
                    "label": {
                        "type": "string",
                        "description": "Object label to count (e.g. 'cup', 'person')",
                    },
                    "window_minutes": {
                        "type": "integer",
                        "description": "Time window in minutes to look back. Default: 60",
                        "default": 60,
                    },
                },
                "required": ["event_log_path", "label"],
            },
        ),
        Tool(
            name="vision.start_watch",
            description=(
                "Start a background monitoring loop that captures frames at regular intervals "
                "and logs detection events to a JSONL file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Object labels to watch for (e.g. ['cup', 'bottle'])",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "Capture interval in seconds. Default: 30",
                        "default": 30,
                    },
                    "cooldown_seconds": {
                        "type": "integer",
                        "description": "Cooldown after detection before next capture. Default: 300",
                        "default": 300,
                    },
                    "event_log_path": {
                        "type": "string",
                        "description": "Path to write detection events. Auto-generated if omitted.",
                    },
                },
                "required": ["source_id", "labels"],
            },
        ),
        Tool(
            name="vision.stop_watch",
            description="Stop a background monitoring loop by watcher ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "watcher_id": {
                        "type": "string",
                        "description": "The watcher ID returned by vision.start_watch",
                    }
                },
                "required": ["watcher_id"],
            },
        ),
    ]


# ── Tool dispatcher ───────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "vision.capture_frame":
            result = await _capture_frame(
                arguments["source_id"],
                arguments.get("save_path"),
            )
        elif name == "vision.detect_objects":
            result = await _detect_objects(
                arguments["frame_path"],
                float(arguments.get("confidence", 0.5)),
            )
        elif name == "vision.analyze_image":
            result = await _analyze_image(
                arguments["frame_path"],
                arguments["prompt"],
            )
        elif name == "vision.compare_frames":
            result = await _compare_frames(
                arguments["frame_path_a"],
                arguments["frame_path_b"],
                arguments.get("prompt"),
            )
        elif name == "vision.count_objects":
            result = await _count_objects(
                arguments["event_log_path"],
                arguments["label"],
                int(arguments.get("window_minutes", 60)),
            )
        elif name == "vision.start_watch":
            result = await _start_watch(
                arguments["source_id"],
                arguments["labels"],
                int(arguments.get("interval_seconds", 30)),
                int(arguments.get("cooldown_seconds", 300)),
                arguments.get("event_log_path"),
            )
        elif name == "vision.stop_watch":
            result = await _stop_watch(arguments["watcher_id"])
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as exc:
        logger.exception("vision tool error in %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ── Implementation ────────────────────────────────────────────────────────────

async def _capture_frame(source_id: str, save_path: str | None) -> dict:
    from core.config import app_config

    root = init_storage(app_config.storage.base_dir)
    if save_path is None:
        frames_dir = root / "data" / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(frames_dir / f"{source_id}_{int(time.time())}.jpg")

    adapter = camera_registry.get(source_id)
    actual_path = adapter.capture_frame(save_path)
    return {
        "frame_path": actual_path,
        "timestamp": _now_iso(),
    }


async def _detect_objects(frame_path: str, confidence: float = 0.5) -> list[dict]:
    from env.state import get_env_profile

    profile = get_env_profile()
    yolo_variant = profile.yolo_variant

    try:
        from ultralytics import YOLO  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is not installed. Install it with: pip install ultralytics"
        ) from exc

    from core.config import app_config
    models_dir = Path(app_config.storage.base_dir).expanduser() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # YOLO auto-downloads to ~/.clawtail/models/ on first use
    model_path = models_dir / f"{yolo_variant}.pt"
    model = YOLO(str(model_path) if model_path.exists() else yolo_variant)

    results = model(frame_path, conf=confidence, verbose=False)
    detections = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            label = r.names[int(box.cls[0])]
            conf = float(box.conf[0])
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
            detections.append({
                "label": label,
                "confidence": round(conf, 4),
                "bbox": [round(x1), round(y1), round(x2), round(y2)],
            })
    return detections


async def _analyze_image(frame_path: str, prompt: str) -> dict:
    import litellm  # type: ignore[import]
    from tools.shared.config import get_tool_config

    cfg = get_tool_config()
    image_data = Path(frame_path).read_bytes()
    b64 = base64.b64encode(image_data).decode("utf-8")

    response = await litellm.acompletion(
        model=cfg.vision_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    analysis_text = response.choices[0].message.content or ""
    # IMPORTANT: base64 data is NOT included in the return value
    return {"analysis_text": analysis_text}


async def _compare_frames(
    frame_path_a: str,
    frame_path_b: str,
    prompt: str | None,
) -> dict:
    import litellm  # type: ignore[import]
    from tools.shared.config import get_tool_config

    cfg = get_tool_config()
    if prompt is None:
        prompt = "Describe the differences between these two images in detail."

    def _encode(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode("utf-8")

    b64_a = _encode(frame_path_a)
    b64_b = _encode(frame_path_b)

    response = await litellm.acompletion(
        model=cfg.vision_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_a}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_b}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    diff_description = response.choices[0].message.content or ""
    return {"diff_description": diff_description}


async def _count_objects(
    event_log_path: str,
    label: str,
    window_minutes: int = 60,
) -> dict:
    from datetime import timedelta, timezone
    from datetime import datetime as dt

    log_path = Path(event_log_path)
    if not log_path.exists():
        return {"count": 0, "window_minutes": window_minutes, "label": label}

    now = dt.now(tz=timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)
    count = 0

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                ts_str = event.get("timestamp", "")
                ts = dt.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    labels_in_event = event.get("labels", [])
                    if label in labels_in_event:
                        count += 1
            except (json.JSONDecodeError, ValueError):
                continue

    return {"count": count, "window_minutes": window_minutes, "label": label}


# ── start_watch / stop_watch (T19) ────────────────────────────────────────────

# Module-level watcher registry: watcher_id → asyncio.Task
_watchers: dict[str, asyncio.Task] = {}


async def _start_watch(
    source_id: str,
    labels: list[str],
    interval_seconds: int = 30,
    cooldown_seconds: int = 300,
    event_log_path: str | None = None,
) -> dict:
    from uuid import uuid4
    from tools.vision.watcher import _watch_loop
    from core.config import app_config
    from core.storage_init import init_storage

    if event_log_path is None:
        root = init_storage(app_config.storage.base_dir)
        log_dir = root / "data" / "watch_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        event_log_path = str(log_dir / f"{source_id}_watch.jsonl")

    watcher_id = str(uuid4())
    task = asyncio.create_task(
        _watch_loop(
            source_id=source_id,
            labels=labels,
            interval_seconds=interval_seconds,
            cooldown_seconds=cooldown_seconds,
            event_log_path=event_log_path,
        ),
        name=f"watcher_{watcher_id}",
    )
    _watchers[watcher_id] = task
    logger.info(
        "vision.start_watch: started watcher %s for %s watching %s",
        watcher_id, source_id, labels,
    )
    return {"watcher_id": watcher_id, "status": "started", "event_log_path": event_log_path}


async def _stop_watch(watcher_id: str) -> dict:
    task = _watchers.pop(watcher_id, None)
    if task is None:
        return {"watcher_id": watcher_id, "status": "not_found"}
    if not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    logger.info("vision.stop_watch: stopped watcher %s", watcher_id)
    return {"watcher_id": watcher_id, "status": "stopped"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(tz=timezone.utc).isoformat()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    camera_registry.initialize()
    from tools.shared.mcp_base import run_server
    asyncio.run(run_server(app))
