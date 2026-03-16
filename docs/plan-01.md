# ClawWithTail — Technical Implementation Plan v0.1 (MVP)

> **Based on**: spec.md v0.1.0-draft
> **Date**: 2026-03-13
> **Status**: Implementation Ready
> **Scope**: MVP (v0.1) — CLI functional, all 3 demo scenarios runnable end-to-end

---

## 0. Reading Guide

This document translates the spec into concrete engineering tasks. It is organized as follows:

- **§1** — Module breakdown and inter-module dependencies
- **§2** — Data models and interface contracts (the "API" between modules)
- **§3** — Module-by-module implementation details
- **§4** — MCP Tool implementation details (all 5 packages)
- **§5** — Demo scenario wiring (how modules connect for each demo)
- **§6** — Development sequence and task assignments
- **§7** — Testing strategy
- **§8** — Configuration reference

---

## 1. Module Breakdown & Dependency Graph

### 1.1 Module List

| Module ID | Path | Description |
|---|---|---|
| `M-ENV` | `env/` | Environment Detector — runs first, produces `env_profile` |
| `M-BUS` | `core/bus/` | Device Data Bus — poll + push, ring buffer |
| `M-ADAPT-CAM` | `adapters/camera/` | Camera device adapters (platform-specific) |
| `M-ADAPT-SEN` | `adapters/sensor/` | Sensor device adapters (WiFi poll, BT, serial) |
| `M-TOOL-VIS` | `tools/vision/` | MCP Tool Package: vision |
| `M-TOOL-SEN` | `tools/sensor/` | MCP Tool Package: sensor |
| `M-TOOL-STO` | `tools/storage/` | MCP Tool Package: storage |
| `M-TOOL-NOT` | `tools/notify/` | MCP Tool Package: notify |
| `M-TOOL-KNO` | `tools/knowledge/` | MCP Tool Package: knowledge |
| `M-LLM` | `core/agent/llm_engine.py` | LiteLLM wrapper, context budget manager |
| `M-AGENT` | `core/agent/` | ReAct loop, tool call dispatcher |
| `M-TASK` | `core/task_runner/` | Task JSON loader, executor, state manager |
| `M-SCHED` | `core/scheduler/` | Cron + event trigger engine |
| `M-CLI` | `cli/` | CLI entry point (Typer) |

### 1.2 Dependency Graph

```
M-CLI
  └─► M-SCHED ──────────────────────────────────────────────────┐
        └─► M-TASK                                               │
              └─► M-AGENT                                        │
                    ├─► M-LLM (LiteLLM)                         │
                    └─► MCP Tools (via MCP protocol)             │
                          ├─► M-TOOL-VIS                         │
                          │     ├─► M-ADAPT-CAM ──► M-BUS        │
                          │     └─► YOLOv8 (local)               │
                          ├─► M-TOOL-SEN                         │
                          │     └─► M-ADAPT-SEN ──► M-BUS        │
                          ├─► M-TOOL-STO (local filesystem)      │
                          ├─► M-TOOL-NOT (Feishu HTTP)           │
                          └─► M-TOOL-KNO (web API + local RAG)   │
                                                                  │
M-ENV ────────────────────────────────────────────────────────────┘
  (injected into all modules at startup via global env_profile)
```

**Startup order**:
1. `M-ENV` — detect environment, produce `env_profile`
2. `M-BUS` — start bus (HTTP webhook server + poll scheduler)
3. `M-ADAPT-*` — register adapters based on `env_profile`
4. `M-TOOL-*` — start MCP tool servers (each as a subprocess or asyncio task)
5. `M-SCHED` — load task configs, register triggers
6. `M-CLI` — hand control to user

---

## 2. Data Models & Interface Contracts

### 2.1 `EnvProfile` (output of M-ENV)

```python
@dataclass
class EnvProfile:
    os: Literal["linux", "windows", "macos"]
    camera_backend: Literal["v4l2", "directshow", "avfoundation", "none"]
    gpu_available: bool
    gpu_type: Literal["cuda", "mps", "none"]
    bluetooth_available: bool
    python_version: str
    detected_cameras: list[dict]      # [{"id": "0", "name": "USB Camera"}]
    detected_serial_ports: list[str]  # ["/dev/ttyUSB0"]
    yolo_variant: Literal["yolov8n", "yolov8s"]  # resolved by detector
```

### 2.2 `BusMessage` (canonical data unit on the Device Data Bus)

```python
@dataclass
class BusMessage:
    device_id: str
    device_type: Literal["camera", "sensor"]
    timestamp: datetime
    payload: BusPayload

@dataclass
class BusPayload:
    type: Literal["frame", "reading"]
    # For frame: local file path (frame already saved to disk by adapter)
    # For reading: numeric value
    data: str | float
    unit: str | None          # e.g. "celsius", "percent", None for frames
    meta: dict                # arbitrary extra fields
```

> **Design note**: Camera frames are **never** passed as base64 through the bus. The adapter saves the JPEG to `~/.clawtail/data/frames/` and puts the file path in `data`. This keeps the bus message small.

### 2.3 `TaskConfig` (loaded from Task JSON)

```python
@dataclass
class TaskConfig:
    task_id: str
    name: str
    description: str
    trigger: TriggerConfig
    context: ContextConfig
    goal: str
    constraints: list[str]
    output: OutputConfig

@dataclass
class TriggerConfig:
    type: Literal["cron", "on_event", "manual"]
    cron: str | None           # cron expression
    event: str | None          # e.g. "device.push", "task.complete", "system.start"
    event_source: str | None   # device_id or task_id

@dataclass
class ContextConfig:
    include_summaries: SummaryContextConfig | None
    include_sensor_stats: SensorStatsContextConfig | None

@dataclass
class OutputConfig:
    save_report: bool
    notify_feishu: bool
    notify_trigger: Literal["always", "on_anomaly", "on_complete"]
```

### 2.4 `AgentRunResult` (output of one Agent execution)

```python
@dataclass
class AgentRunResult:
    task_id: str
    run_id: str               # UUID
    started_at: datetime
    finished_at: datetime
    status: Literal["success", "failed", "step_limit_reached"]
    tool_calls: list[ToolCallRecord]
    final_summary: str        # LLM's final text output
    report_path: str | None
    notification_sent: bool
    error: str | None
```

---

## 3. Module Implementation Details

### 3.1 M-ENV: Environment Detector

**File**: `env/detector.py`

**Responsibilities**:
- Detect OS via `platform.system()`
- Detect GPU: try `import torch; torch.cuda.is_available()` for CUDA; `torch.backends.mps.is_available()` for Apple Silicon MPS
- Detect camera backend: map OS → backend; probe `cv2.VideoCapture(0)` to confirm at least one camera is accessible
- Detect Bluetooth: try `import bluetooth` (PyBluez) or `bleak`; catch ImportError gracefully
- Enumerate serial ports via `serial.tools.list_ports`
- Resolve `yolo_variant`: `yolov8s` if GPU available, else `yolov8n`
- Check `config.yaml` for `tool_variant_overrides` and apply them

**Output**: singleton `env_profile` stored in `env/state.py`, importable by all modules.

**Error handling**: If a probe fails (e.g., no camera found), log a warning and set the field to `"none"` — never crash startup.

```python
# env/detector.py (skeleton)
def detect() -> EnvProfile:
    os_name = _detect_os()
    gpu_type = _detect_gpu()
    camera_backend = _detect_camera_backend(os_name)
    bt_available = _detect_bluetooth()
    cameras = _enumerate_cameras()
    serial_ports = _enumerate_serial_ports()
    yolo_variant = _resolve_yolo_variant(gpu_type)
    return EnvProfile(
        os=os_name,
        camera_backend=camera_backend,
        gpu_available=(gpu_type != "none"),
        gpu_type=gpu_type,
        bluetooth_available=bt_available,
        python_version=platform.python_version(),
        detected_cameras=cameras,
        detected_serial_ports=serial_ports,
        yolo_variant=yolo_variant,
    )
```

---

### 3.2 M-BUS: Device Data Bus

**Files**: `core/bus/bus.py`, `core/bus/webhook_server.py`, `core/bus/poll_manager.py`

**Architecture**:

```
┌─────────────────────────────────────────────────────┐
│                  Device Data Bus                    │
│                                                     │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │ Poll Manager │    │ Webhook Server (FastAPI)  │   │
│  │              │    │ POST /webhook/{device_id} │   │
│  │ per-device   │    │                          │   │
│  │ asyncio loop │    └──────────┬───────────────┘   │
│  └──────┬───────┘               │                   │
│         │ BusMessage            │ BusMessage         │
│         └──────────┬────────────┘                   │
│                    ▼                                 │
│           ┌─────────────────┐                       │
│           │   Ring Buffer   │  (asyncio.Queue,       │
│           │   per device    │   max 1000 msgs)       │
│           └────────┬────────┘                       │
│                    │ subscribe(device_id)            │
│                    ▼                                 │
│           MCP Tool Packages (consumers)             │
└─────────────────────────────────────────────────────┘
```

**Key design decisions**:
- Ring buffer implemented as `asyncio.Queue(maxsize=1000)` per device. When full, oldest message is dropped (non-blocking).
- Webhook server runs on `localhost:17171` (configurable). Only loopback — not exposed to LAN by default.
- Poll Manager reads `devices.yaml`, spawns one asyncio task per `wifi_poll` device.
- `sensor.read_latest` MCP tool calls `bus.get_latest(device_id)` — returns the most recent message without consuming it.
- `sensor.read_history` calls `bus.get_history(device_id, from, to)` — reads from the persisted JSONL log (bus writes all messages to `~/.clawtail/data/sensor_logs/{device_id}.jsonl`).

**Persistence**: Every `BusMessage` of type `reading` is appended to `~/.clawtail/data/sensor_logs/{device_id}.jsonl` immediately on receipt. Frames are saved to disk by the adapter before the message is put on the bus.

---

### 3.3 M-ADAPT-CAM: Camera Adapters

**Files**: `adapters/camera/base.py`, `adapters/camera/v4l2.py`, `adapters/camera/directshow.py`, `adapters/camera/avfoundation.py`

**Base interface**:

```python
class CameraAdapter(ABC):
    def __init__(self, device_config: dict, env_profile: EnvProfile): ...

    def capture_frame(self, save_path: str) -> str:
        """Capture one frame, save as JPEG to save_path, return actual path."""
        ...

    def is_available(self) -> bool:
        """Return True if the camera device is accessible."""
        ...
```

**Platform implementations**:

| File | Backend | Notes |
|---|---|---|
| `v4l2.py` | `cv2.VideoCapture(source)` on Linux | `source` = `/dev/video0` or index |
| `directshow.py` | `cv2.VideoCapture(index, cv2.CAP_DSHOW)` on Windows | DirectShow backend flag |
| `avfoundation.py` | `cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)` on macOS | AVFoundation backend flag |

All three use OpenCV under the hood — the difference is the backend flag and device path format. The `M-ENV` detector selects the correct class at startup; `M-TOOL-VIS` only ever calls `CameraAdapter.capture_frame()`.

---

### 3.4 M-ADAPT-SEN: Sensor Adapters

**Files**: `adapters/sensor/base.py`, `adapters/sensor/wifi_poll.py`, `adapters/sensor/bluetooth.py`, `adapters/sensor/serial_adapter.py`

**Base interface**:

```python
class SensorAdapter(ABC):
    def poll(self) -> BusMessage:
        """Fetch one reading and return as BusMessage."""
        ...

    def is_available(self) -> bool: ...
```

**WiFi Poll adapter** (`wifi_poll.py`):
- Makes HTTP GET to `poll_url` from `devices.yaml`
- Parses JSON response: expects `{"value": float, "unit": "string"}`
- Wraps in `BusMessage` and returns

**Bluetooth adapter** (`bluetooth.py`):
- Uses `bleak` (async BLE library, cross-platform)
- Reads from a configured GATT characteristic UUID
- Only instantiated if `env_profile.bluetooth_available == True`

**Serial adapter** (`serial_adapter.py`):
- Uses `pyserial`
- Reads line-delimited JSON from serial port
- Useful for ESP32/Arduino devices connected via USB

---

### 3.5 M-LLM: LLM Engine

**File**: `core/agent/llm_engine.py`

**Responsibilities**:
- Wrap LiteLLM's `completion()` call
- Enforce context window budget (see spec §3.3)
- Manage prompt templates (system prompt, task goal injection)
- Handle tool call response parsing (OpenAI function calling format)
- Retry on rate limit (exponential backoff, max 3 retries)

**Context budget enforcement**:

```python
class ContextBudget:
    SYSTEM_PROMPT_MAX = 1000      # tokens
    SUMMARIES_MAX     = 2000      # tokens
    SENSOR_STATS_MAX  = 500       # tokens
    TOOL_HISTORY_MAX  = 3000      # tokens
    TOTAL_MAX         = 8000      # tokens (conservative, works for all models)

    def build_messages(self, task: TaskConfig, context: AgentContext) -> list[dict]:
        """Assemble messages list, truncating each section to its budget."""
        ...
```

**Model configuration** (from `config.yaml`):

```yaml
llm:
  default_model: "gpt-4o"          # LiteLLM model string
  vision_model: "gpt-4o"           # Used for vision.analyze_image
  fallback_model: "gpt-4o-mini"    # Used when default fails
  api_keys:
    openai: "${OPENAI_API_KEY}"
    anthropic: "${ANTHROPIC_API_KEY}"
```

LiteLLM handles the actual API routing — `M-LLM` only needs to pass the model string.

---

### 3.6 M-AGENT: ReAct Orchestration Loop

**Files**: `core/agent/agent.py`, `core/agent/react_loop.py`, `core/agent/tool_dispatcher.py`

**ReAct loop implementation**:

```
┌─────────────────────────────────────────────────────────┐
│                    ReAct Loop                           │
│                                                         │
│  Input: TaskConfig + injected context                   │
│                                                         │
│  Step 1: REASON                                         │
│    LLM receives: system_prompt + goal + context         │
│    LLM outputs: thought + tool_call (or final_answer)   │
│                                                         │
│  Step 2: ACT                                            │
│    ToolDispatcher routes tool_call to correct MCP server│
│    Calls tool via MCP protocol (JSON-RPC over stdio)    │
│                                                         │
│  Step 3: OBSERVE                                        │
│    Tool result appended to message history              │
│    Loop back to Step 1                                  │
│                                                         │
│  Termination conditions:                                │
│    - LLM outputs final_answer (no tool call)            │
│    - Step count >= task.max_steps (default: 20)         │
│    - Hard timeout (default: 10 minutes per run)         │
└─────────────────────────────────────────────────────────┘
```

**Tool Dispatcher**:
- Maintains a registry of all available MCP tools (populated at startup from all running MCP servers)
- Routes `tool_name` → correct MCP server process
- Handles MCP JSON-RPC call/response serialization
- Returns tool result as a string (JSON-serialized) back to the ReAct loop

**Self-Planning Mode** (triggered when `task.trigger.type == "self_plan"`):

```python
async def self_plan(goal: str) -> TaskConfig:
    """
    Run a planning agent that uses knowledge tools to construct a TaskConfig.
    The planning agent has access to: knowledge.*, storage.list_summaries
    It outputs a TaskConfig JSON which is validated against the schema.
    The result is saved to ~/.clawtail/tasks/{generated_id}.json
    """
    ...
```

---

### 3.7 M-TASK: Task Runner

**Files**: `core/task_runner/runner.py`, `core/task_runner/context_builder.py`, `core/task_runner/state.py`

**Responsibilities**:
- Load and validate Task JSON against JSON Schema
- Build `AgentContext` by fetching summaries and sensor stats per `task.context` config
- Invoke `M-AGENT` with the assembled context
- Persist `AgentRunResult` to `~/.clawtail/logs/runs/{task_id}/{run_id}.json`
- Handle output policy: save report, send Feishu notification

**Context builder** (`context_builder.py`):

```python
class ContextBuilder:
    def build(self, task: TaskConfig) -> AgentContext:
        context = AgentContext()

        # Inject recent summaries (text only, no images)
        if task.context.include_summaries:
            summaries = storage.list_summaries(
                category=task.context.include_summaries.category,
                last_n=task.context.include_summaries.last_n
            )
            context.summaries = [s.content for s in summaries]

        # Inject sensor stats (aggregated numbers, no raw tables)
        if task.context.include_sensor_stats:
            for device_id in task.context.include_sensor_stats.device_ids:
                stats = bus.get_stats(
                    device_id,
                    window_minutes=task.context.include_sensor_stats.window_minutes
                )
                context.sensor_stats[device_id] = stats

        return context
```

---

### 3.8 M-SCHED: Scheduler

**Files**: `core/scheduler/scheduler.py`, `core/scheduler/event_bus.py`

**Cron triggers**: Uses `APScheduler` (AsyncIOScheduler) — battle-tested, supports cron expressions, asyncio-native.

**Event triggers**: Internal pub/sub via `event_bus.py`. Events:
- `system.start` — fired once at startup
- `device.push:{device_id}` — fired when a push message arrives on the bus
- `task.complete:{task_id}` — fired when a task run finishes

**Scheduler config** (from Task JSON):

```python
# cron trigger
scheduler.add_job(
    task_runner.run,
    CronTrigger.from_crontab(task.trigger.cron),
    args=[task],
    id=task.task_id
)

# event trigger
event_bus.subscribe(task.trigger.event, lambda: task_runner.run(task))
```

---

### 3.9 M-CLI: Command Line Interface

**File**: `cli/main.py` — built with **Typer**

**Commands**:

```
clawtail start                    # Start the daemon (bus + scheduler + MCP servers)
clawtail stop                     # Stop the daemon

clawtail task list                # List all configured tasks
clawtail task run <task_id>       # Manually trigger a task run
clawtail task show <task_id>      # Show task config
clawtail task generate "<goal>"   # LLM-assisted task generation (Self-Planning Mode)
clawtail task validate <path>     # Validate a Task JSON file against schema

clawtail device list              # List registered devices and their status
clawtail device test <device_id>  # Test device connectivity (capture one frame / one reading)

clawtail log list                 # List recent task runs
clawtail log show <run_id>        # Show full run log (tool calls, LLM reasoning, result)

clawtail env show                 # Show detected env_profile
clawtail env check                # Re-run environment detection
```

---

## 4. MCP Tool Package Implementation Details

Each Tool Package is an independent Python module that registers its tools with the MCP server. All packages share a common startup pattern:

```python
# tools/{package}/server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("{package}-tools")

@app.tool()
async def tool_name(param1: str, param2: int) -> dict:
    ...

async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())
```

### 4.1 `vision` Tool Package

**File**: `tools/vision/server.py`

#### `vision.capture_frame`

```python
@app.tool()
async def capture_frame(source_id: str, save_path: str | None = None) -> dict:
    """
    Capture one frame from the specified camera source.
    Returns: {"frame_path": str, "timestamp": str}
    """
    adapter = camera_registry.get(source_id)  # resolved by env_profile at startup
    path = save_path or _auto_path(source_id)
    actual_path = adapter.capture_frame(path)
    return {"frame_path": actual_path, "timestamp": datetime.utcnow().isoformat()}
```

#### `vision.detect_objects`

```python
@app.tool()
async def detect_objects(frame_path: str, confidence: float = 0.5) -> list[dict]:
    """
    Run YOLOv8 object detection on a frame.
    Returns: [{"label": str, "confidence": float, "bbox": [x1,y1,x2,y2]}]
    """
    model = yolo_registry.get_model()  # yolov8n or yolov8s, resolved at startup
    results = model(frame_path, conf=confidence)
    return _parse_yolo_results(results)
```

#### `vision.analyze_image`

```python
@app.tool()
async def analyze_image(frame_path: str, prompt: str) -> dict:
    """
    Send image to vision LLM with a prompt. Image is encoded as base64 for the API call
    but NEVER stored in context or returned as base64.
    Returns: {"analysis_text": str}
    """
    with open(frame_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    response = await litellm.acompletion(
        model=config.vision_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]
        }]
    )
    return {"analysis_text": response.choices[0].message.content}
```

#### `vision.start_watch` (background watcher for Drinking Demo)

```python
@app.tool()
async def start_watch(
    source_id: str,
    labels: list[str],
    interval_seconds: int = 30,
    cooldown_seconds: int = 300,
    event_log_path: str | None = None
) -> dict:
    """
    Start a background watcher that samples frames at interval_seconds,
    runs detect_objects, and logs events when any of `labels` are detected.
    After a detection, sleeps for cooldown_seconds before resuming.
    Returns: {"watcher_id": str, "status": "started"}
    """
    watcher_id = str(uuid4())
    log_path = event_log_path or _default_event_log_path(source_id)
    asyncio.create_task(_watch_loop(watcher_id, source_id, labels, interval_seconds, cooldown_seconds, log_path))
    return {"watcher_id": watcher_id, "status": "started"}

async def _watch_loop(watcher_id, source_id, labels, interval, cooldown, log_path):
    while True:
        frame_path, ts = await _capture(source_id)
        detections = await _detect(frame_path)
        matched = [d for d in detections if d["label"] in labels]
        if matched:
            _append_event_log(log_path, ts, matched)
            await asyncio.sleep(cooldown)
        else:
            await asyncio.sleep(interval)
```

> **Q8 resolution**: `vision.start_watch` uses `asyncio.create_task` — runs as a coroutine within the same event loop as the MCP server. No subprocess needed. The watcher ID is stored in a module-level dict for future `vision.stop_watch` support.

---

### 4.2 `sensor` Tool Package

**File**: `tools/sensor/server.py`

All sensor tools read from the Device Data Bus, never from device SDKs directly.

#### `sensor.read_latest`

```python
@app.tool()
async def read_latest(device_id: str) -> dict:
    """Returns the most recent reading from the bus ring buffer."""
    msg = bus.get_latest(device_id)
    if msg is None:
        raise ToolError(f"No data available for device {device_id}")
    return {"value": msg.payload.data, "unit": msg.payload.unit, "timestamp": msg.timestamp.isoformat()}
```

#### `sensor.get_stats`

```python
@app.tool()
async def get_stats(device_id: str, from_iso: str, to_iso: str) -> dict:
    """
    Reads from persisted JSONL log (not ring buffer) for historical range.
    Returns: {"min": float, "max": float, "avg": float, "trend": "rising|falling|stable"}
    """
    readings = _load_jsonl_range(device_id, from_iso, to_iso)
    values = [r["value"] for r in readings]
    trend = _compute_trend(values)
    return {"min": min(values), "max": max(values), "avg": sum(values)/len(values), "trend": trend}
```

---

### 4.3 `storage` Tool Package

**File**: `tools/storage/server.py`

All paths are under `~/.clawtail/`. The tool package never accepts absolute paths from the LLM — it constructs paths internally to prevent path traversal.

#### `storage.save_summary`

```python
@app.tool()
async def save_summary(content: str, category: str, tags: list[str] | None = None) -> dict:
    summary_id = str(uuid4())
    meta = {"id": summary_id, "category": category, "tags": tags or [], "created_at": utcnow()}
    path = SUMMARIES_DIR / f"{summary_id}.json"
    path.write_text(json.dumps({"meta": meta, "content": content}))
    return {"summary_id": summary_id, "path": str(path)}
```

#### `storage.save_report`

```python
@app.tool()
async def save_report(content: str, title: str, task_id: str) -> dict:
    date_str = date.today().isoformat()
    filename = f"{date_str}_{task_id}_{slugify(title)}.md"
    path = REPORTS_DIR / filename
    path.write_text(content)
    return {"report_path": str(path)}
```

---

### 4.4 `notify` Tool Package

**File**: `tools/notify/server.py`

#### `notify.feishu_send`

```python
@app.tool()
async def feishu_send(message: str, webhook_url: str | None = None) -> dict:
    url = webhook_url or config.feishu_default_webhook
    payload = {"msg_type": "text", "content": {"text": message}}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=10)
    return {"success": resp.status_code == 200, "status_code": resp.status_code}
```

#### `notify.feishu_send_report`

```python
@app.tool()
async def feishu_send_report(title: str, summary: str, report_path: str) -> dict:
    """
    Sends a rich Feishu card message with title, summary text, and report file path.
    The report_path is included as a reference (Feishu does not host files; path is informational).
    """
    message = f"📋 **{title}**\n\n{summary}\n\n📁 Report saved: `{report_path}`"
    return await feishu_send(message)
```

---

### 4.5 `knowledge` Tool Package

**File**: `tools/knowledge/server.py`

#### `knowledge.search_web`

```python
@app.tool()
async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Uses configured search provider (Tavily API recommended for MVP — Q7 resolution).
    Returns: [{"title": str, "snippet": str, "url": str}]
    """
    client = TavilyClient(api_key=config.tavily_api_key)
    results = client.search(query, max_results=max_results)
    return [{"title": r["title"], "snippet": r["content"], "url": r["url"]} for r in results["results"]]
```

> **Q7 resolution**: Tavily API is selected for MVP. It is purpose-built for LLM agents (returns clean text snippets, not raw HTML), has a generous free tier, and requires no self-hosting. SerpAPI or Searxng can be swapped in via config.

#### `knowledge.identify_plant`

```python
@app.tool()
async def identify_plant(frame_path: str) -> dict:
    """
    Uses vision LLM to identify plant species from an image.
    Returns: {"species": str, "common_name": str, "confidence": str, "care_summary": str}
    """
    prompt = (
        "Identify the plant species in this image. "
        "Return a JSON object with fields: species (scientific name), "
        "common_name, confidence (high/medium/low), care_summary (2 sentences)."
    )
    result = await analyze_image(frame_path, prompt)  # reuses vision tool logic
    return json.loads(_extract_json(result["analysis_text"]))
```

#### `knowledge.fetch_care_guide`

```python
@app.tool()
async def fetch_care_guide(species_name: str) -> dict:
    """
    Fetches structured care guide. First checks local KB cache, then falls back to web search.
    Returns: {"watering": str, "light": str, "temperature": str, "humidity": str, "notes": str}
    """
    # Check local cache first
    cached = _load_care_guide_cache(species_name)
    if cached:
        return cached

    # Web search fallback
    results = await search_web(f"{species_name} plant care guide watering light temperature")
    guide = await _llm_extract_care_guide(species_name, results)
    _save_care_guide_cache(species_name, guide)
    return guide
```

#### `knowledge.search_local_kb`

```python
@app.tool()
async def search_local_kb(query: str, category: str | None = None) -> list[dict]:
    """
    Simple keyword + recency search over saved summaries (no vector DB for MVP).
    Post-MVP: replace with embedding-based RAG.
    Returns: [{"summary_id": str, "relevance_score": float, "snippet": str}]
    """
    summaries = _load_all_summaries(category)
    scored = [(s, _keyword_score(query, s["content"])) for s in summaries]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{"summary_id": s["meta"]["id"], "relevance_score": score, "snippet": s["content"][:300]}
            for s, score in scored[:10] if score > 0]
```

---

## 5. Demo Scenario Wiring

### 5.1 Plant Watering Reminder — End-to-End Flow

```
User runs: clawtail task generate "Monitor and care for the plant on my desk"
  │
  ▼
Self-Planning Agent starts
  ├─► knowledge.identify_plant(frame_path=vision.capture_frame("desk_camera"))
  │     → {"species": "Monstera deliciosa", "common_name": "Swiss Cheese Plant", ...}
  ├─► knowledge.fetch_care_guide("Monstera deliciosa")
  │     → {"watering": "every 1-2 weeks", "soil_moisture_threshold": "30%", ...}
  ├─► knowledge.search_web("Monstera deliciosa care 2025")
  │     → [supplementary tips]
  └─► LLM synthesizes TaskConfig JSON → saved to ~/.clawtail/tasks/plant_monitor_auto.json

Scheduler loads plant_monitor_auto.json → registers cron every 2 hours

Every 2 hours, Task Runner fires:
  Agent receives goal + care guide context + last 3 summaries
  ├─► vision.capture_frame("desk_camera") → frame_path
  ├─► vision.analyze_image(frame_path, "Describe the plant's visual health indicators: leaf color, drooping, spots")
  │     → "Leaves appear slightly drooping, color is healthy green, no visible spots"
  ├─► sensor.read_latest("plant_soil_sensor") → {"value": 22.5, "unit": "percent"}
  ├─► sensor.get_stats("plant_soil_sensor", last_2h) → {"min": 20, "max": 25, "avg": 22, "trend": "falling"}
  ├─► knowledge.search_local_kb("plant health summary", category="plant_monitor")
  │     → [last 3 summaries]
  ├─► storage.save_summary("Leaves slightly drooping. Soil moisture 22%, falling trend. ...")
  └─► [if soil < 30% threshold] notify.feishu_send("🌿 Your Monstera needs water! Soil moisture: 22%")
```

### 5.2 Chemistry Experiment Monitor — End-to-End Flow

```
Task: chemistry_monitor.json (pre-authored, cron every 15 minutes)

Every 15 minutes:
  ├─► vision.capture_frame("lab_camera") → current_frame
  ├─► storage.list_summaries(category="chem_experiment", last_n=1) → prev_summary
  ├─► vision.compare_frames(prev_frame_path, current_frame) → diff_description
  ├─► vision.analyze_image(current_frame, "Describe observable state: color, precipitate, bubbles, volume")
  │     → "Yellow precipitate forming at bottom, solution color changed from clear to pale yellow"
  ├─► storage.save_summary(f"[{timestamp}] {analysis_text}", category="chem_experiment")
  └─► [if significant change detected] notify.feishu_send("⚗️ Significant change detected: yellow precipitate forming")

End-of-experiment (manual trigger or scheduled):
  ├─► storage.list_summaries(category="chem_experiment", last_n=50) → all_summaries
  ├─► LLM generates Markdown report from all_summaries
  ├─► storage.save_report(report_content, title="Experiment Log", task_id="chemistry_monitor")
  └─► notify.feishu_send_report("Experiment Complete", "Yellow precipitate formed at T+2h...", report_path)
```

### 5.3 Drinking Water Reminder — End-to-End Flow

```
System startup fires event: system.start

Watcher Task (on_event: system.start):
  └─► vision.start_watch(
        source_id="desk_camera",
        labels=["cup", "bottle", "drinking glass"],
        interval_seconds=30,
        cooldown_seconds=300,
        event_log_path="~/.clawtail/data/drink_events.jsonl"
      )
  Background loop runs forever:
    Every 30s: capture frame → detect_objects → if cup/bottle near face → log event → sleep 5min

Summarizer Task (cron: every 90 minutes):
  Agent receives goal: "Review drinking activity log for past 90 minutes..."
  ├─► vision.count_objects(event_log_path, label="any", window_minutes=90) → {"count": 3}
  ├─► storage.list_summaries(category="hydration", last_n=3) → recent summaries
  ├─► [LLM reasons: 3 events in 90 min = adequate hydration]
  ├─► storage.save_summary("90-min window: 3 drinking events detected. Hydration adequate.", category="hydration")
  └─► [if count < 1] notify.feishu_send("💧 Hydration reminder: No drinking detected in the past 90 minutes!")
```

---

## 6. Development Sequence & Task Assignments

### Sprint 0 — Foundation (Week 1-2)

| Task | Module | Owner Suggestion | Notes |
|---|---|---|---|
| S0-1 | Repo scaffold, `pyproject.toml`, dev environment | `M-CLI` | Python 3.11+, uv or poetry |
| S0-2 | `config.yaml` + `devices.yaml` schema and loader | `core/config/` | Pydantic models |
| S0-3 | Environment Detector | `M-ENV` | All 3 OS targets |
| S0-4 | Data models (`BusMessage`, `TaskConfig`, etc.) | `core/models/` | Shared across all modules |
| S0-5 | Local storage directory init | `M-TOOL-STO` | Create `~/.clawtail/` tree |

### Sprint 1 — Device Layer (Week 3-4)

| Task | Module | Notes |
|---|---|---|
| S1-1 | Camera adapters (v4l2 + directshow + avfoundation) | `M-ADAPT-CAM` | Test on all 3 OS |
| S1-2 | WiFi Poll sensor adapter | `M-ADAPT-SEN` | Mock server for testing |
| S1-3 | Device Data Bus (ring buffer + JSONL persistence) | `M-BUS` | asyncio.Queue |
| S1-4 | Webhook server (FastAPI, localhost only) | `M-BUS` | Push path |
| S1-5 | `clawtail device list` + `clawtail device test` CLI commands | `M-CLI` | Early validation |

### Sprint 2 — Tool Packages (Week 5-7)

| Task | Module | Notes |
|---|---|---|
| S2-1 | `vision` tool package (capture, detect, analyze, compare, count) | `M-TOOL-VIS` | YOLOv8 integration |
| S2-2 | `sensor` tool package (read_latest, read_history, get_stats) | `M-TOOL-SEN` | Reads from bus |
| S2-3 | `storage` tool package (save/read summary, save/read report) | `M-TOOL-STO` | Path safety |
| S2-4 | `notify` tool package (feishu_send, feishu_send_report) | `M-TOOL-NOT` | Feishu webhook |
| S2-5 | `knowledge` tool package (search_web, identify_plant, fetch_care_guide, search_local_kb) | `M-TOOL-KNO` | Tavily API |
| S2-6 | `vision.start_watch` background watcher | `M-TOOL-VIS` | asyncio task |

### Sprint 3 — Agent & Orchestration (Week 8-10)

| Task | Module | Notes |
|---|---|---|
| S3-1 | LiteLLM wrapper + context budget manager | `M-LLM` | Multi-model config |
| S3-2 | ReAct loop + tool dispatcher | `M-AGENT` | MCP JSON-RPC |
| S3-3 | Task JSON schema + loader + validator | `M-TASK` | JSON Schema |
| S3-4 | Context builder (summaries + sensor stats injection) | `M-TASK` | Budget enforcement |
| S3-5 | APScheduler integration (cron + event triggers) | `M-SCHED` | |
| S3-6 | Self-Planning Mode | `M-AGENT` | Planning agent |

### Sprint 4 — Integration & Demo (Week 11-12)

| Task | Notes |
|---|---|
| S4-1 | Wire Demo 1: Plant Watering (Self-Planning flow) | End-to-end test |
| S4-2 | Wire Demo 2: Chemistry Monitor (pre-authored Task JSON) | End-to-end test |
| S4-3 | Wire Demo 3: Drinking Water (two-tier watcher + summarizer) | End-to-end test |
| S4-4 | Full CLI command set | All commands functional |
| S4-5 | `clawtail task generate` (LLM-assisted Task generation) | Self-Planning via CLI |
| S4-6 | README + demo video | Public release prep |

---

## 7. Testing Strategy

### 7.1 Unit Tests

Each module has a `tests/unit/test_{module}.py`. Key test cases:

| Module | Key Test Cases |
|---|---|
| `M-ENV` | Mock `platform.system()`, `torch.cuda.is_available()` → verify correct `env_profile` |
| `M-BUS` | Ring buffer overflow behavior; JSONL persistence; push webhook receives message |
| `M-TOOL-VIS` | `capture_frame` with mock adapter; `detect_objects` with fixture image; `analyze_image` with mocked LiteLLM |
| `M-TOOL-SEN` | `read_latest` with empty buffer (expect ToolError); `get_stats` with fixture JSONL |
| `M-TASK` | Task JSON validation (valid + invalid schemas); context builder token budget enforcement |
| `M-AGENT` | ReAct loop terminates on `final_answer`; terminates on step limit; tool dispatcher routes correctly |

### 7.2 Integration Tests

**`tests/integration/test_demo_plant.py`**:
- Uses mock camera adapter (returns fixture JPEG)
- Uses mock sensor adapter (returns fixture readings)
- Uses mocked LiteLLM (returns scripted responses)
- Asserts: summary saved, Feishu call made when soil < threshold

**`tests/integration/test_demo_drinking.py`**:
- Starts `vision.start_watch` with mock camera
- Injects 3 detection events into event log
- Triggers summarizer task
- Asserts: no Feishu call (3 events = adequate)
- Injects 0 events → asserts Feishu call made

### 7.3 Hardware-in-the-Loop Tests (Manual)

Run on actual hardware before release:
- USB camera capture on Linux, Windows, macOS
- WiFi sensor poll (ESP32 mock server)
- Feishu webhook delivery

---

## 8. Configuration Reference

### `config/config.yaml`

```yaml
# LLM configuration
llm:
  default_model: "gpt-4o"
  vision_model: "gpt-4o"
  fallback_model: "gpt-4o-mini"
  api_keys:
    openai: "${OPENAI_API_KEY}"
    anthropic: "${ANTHROPIC_API_KEY}"
    gemini: "${GEMINI_API_KEY}"

# Notification
notify:
  feishu_default_webhook: "${FEISHU_WEBHOOK_URL}"

# Knowledge tools
knowledge:
  search_provider: "tavily"   # tavily | serpapi | searxng
  tavily_api_key: "${TAVILY_API_KEY}"

# Device Data Bus
bus:
  webhook_port: 17171
  ring_buffer_size: 1000

# Storage
storage:
  base_dir: "~/.clawtail"

# Tool variant overrides (optional)
tool_variant_overrides:
  vision.yolo: null   # null = auto-detect
```

### `config/devices.yaml`

```yaml
devices:
  - id: "desk_camera"
    type: "camera"
    transport: "usb"
    source: "0"                    # device index (auto on Windows/macOS) or /dev/video0

  - id: "plant_soil_sensor"
    type: "sensor"
    subtype: "soil_moisture"
    transport: "wifi_poll"
    poll_url: "http://192.168.1.42/api/moisture"
    poll_interval_seconds: 120

  - id: "lab_temp_sensor"
    type: "sensor"
    subtype: "temperature"
    transport: "wifi_push"
    push_webhook_path: "/webhook/lab_temp"
```

---

## 9. Open Questions Resolution Status

| # | Question | Resolution in This Plan |
|---|---|---|
| Q1 | Final project name | ClawWithTail (placeholder, rename pre-v0.1 release) |
| Q2 | OS priority order | Linux > macOS > Windows (all 3 supported in MVP) |
| Q3 | YOLO weight distribution | Download on first run via `ultralytics` auto-download; cached in `~/.clawtail/models/` |
| Q4 | Feishu webhook config | Single global default in `config.yaml`; per-task override via `output.notify.webhook_url` in Task JSON |
| Q5 | Task JSON versioning | `"schema_version": "1.0"` field in Task JSON; migration scripts in `core/task_runner/migrations/` |
| Q6 | Visual Task editor | Post-MVP (v0.3); JSON schema designed to map 1:1 to React Flow nodes |
| Q7 | `knowledge.search_web` provider | Tavily API for MVP (see §4.5) |
| Q8 | `vision.start_watch` process model | `asyncio.create_task` within MCP server event loop (see §4.1) |
