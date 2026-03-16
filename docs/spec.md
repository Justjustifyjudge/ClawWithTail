# ClawWithTail — Project Specification

> **Version**: 0.1.0-draft
> **Date**: 2026-03-13
> **Status**: Draft — Under Review
> **License**: GPL-3.0

---

## 1. Project Overview

### 1.1 Vision

ClawWithTail is an open-source, locally-deployed AI Agent platform that bridges large language models (LLMs) and physical-world IoT devices. It enables autonomous, continuous perception of the physical environment — capturing data from cameras and sensors — and delivers intelligent analysis, reports, and alerts without requiring human supervision.

> **Core positioning**: An asynchronous intelligent monitoring and reporting system. It is NOT a real-time control system. The LLM's role is perception, reasoning, and reporting — not millisecond-level actuation.

### 1.2 Design Philosophy

1. **Atomic Tools, Composable Tasks**: MCP Tools are generic, reusable primitives (e.g., `vision.detect_objects`, `sensor.read_temperature`). They must not be designed for a single specific use case. Users compose Tools into Tasks via JSON configuration.
2. **LLM as Orchestrator**: The Agent layer uses LLM reasoning to decide which Tools to call, in what order, and how to interpret results. Business logic lives in the LLM's reasoning, not in hardcoded pipelines.
3. **LLM as Self-Planner**: For open-ended goals (e.g., "care for this plant"), the Agent can autonomously construct a Task workflow at runtime by querying knowledge tools, identifying context, and composing a plan — without a pre-authored Task JSON.
4. **Physical World is Read-Only (MVP)**: MVP scope is strictly limited to sensing and reporting. No actuators, no write-back to physical devices.
5. **Context Stays Lean**: Raw images and time-series tables are never injected into LLM context. Only text summaries and file references are passed. The LLM fetches raw data on demand via Tool calls.
6. **Everything is a MCP Tool**: All capabilities exposed to the Agent must be registered as standard MCP protocol tools. No internal shortcut functions.
7. **Environment-Aware Tool Selection**: On startup, the system detects the host OS, hardware capabilities (GPU/CPU), and available device APIs. Tool implementations are selected automatically to match the environment. Users never need to configure platform-specific details manually.

### 1.3 Key Differentiators

| Dimension | ClawWithTail | Typical AI Agent Frameworks |
|---|---|---|
| Sensing layer | Physical cameras + IoT sensors | Digital APIs only |
| Deployment | Local PC, edge-first | Cloud-first |
| Tool design | Atomic, domain-agnostic | Often task-specific |
| Task authoring | JSON config + LLM-assisted generation | Code or proprietary DSL |
| Context strategy | Summary-only, on-demand raw fetch | Often dumps raw data |

---

## 2. Architecture

### 2.1 Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Interface Layer                  │
│          CLI (MVP)  →  Web UI (Post-MVP)                 │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                   Agent Orchestration Layer              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ Task Runner │  │ LLM Engine   │  │ Scheduler      │  │
│  │ (JSON→flow) │  │ (LiteLLM)    │  │ (cron+event)   │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│  ┌──────────────────────────────────────────────────┐    │
│  │ Environment Detector (OS / GPU / Device API)     │    │
│  └──────────────────────────────────────────────────┘    │
└───────────────────────────┬─────────────────────────────┘
                            │ MCP Protocol
┌───────────────────────────▼─────────────────────────────┐
│                     MCP Tool Layer                       │
│  ┌──────────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ Vision Tools │  │ Sensor Tools│  │ Storage Tools  │  │
│  │ (camera,     │  │ (temp,      │  │ (read/write    │  │
│  │  detection,  │  │  humidity,  │  │  local files,  │  │
│  │  analysis)   │  │  soil)      │  │  summaries)    │  │
│  └──────────────┘  └─────────────┘  └────────────────┘  │
│  ┌──────────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ Notify Tools │  │ Local Model │  │ Knowledge Tools│  │
│  │ (Feishu,     │  │ Tools       │  │ (web search,   │  │
│  │  report gen) │  │ (YOLOv8)    │  │  identify,RAG) │  │
│  └──────────────┘  └─────────────┘  └────────────────┘  │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                  Device Data Bus                         │
│   Poll (WiFi/BT pull)  ←→  Push (device webhook)        │
│   Unified data stream regardless of transport           │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                  Physical Device Layer                   │
│   USB Camera / IP Camera / ESP32 / Raspberry Pi          │
│   Temperature Sensor / Humidity Sensor / Soil Sensor     │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Component Descriptions

#### Agent Orchestration Layer

| Component | Responsibility |
|---|---|
| **Task Runner** | Loads Task JSON config, resolves tool call graph, manages execution state |
| **LLM Engine** | Wraps LiteLLM, handles multi-model abstraction, manages prompt templates and context window budget |
| **Scheduler** | Triggers Tasks on cron schedule or event signal; supports: `cron`, `on_event`, `on_task_complete` |
| **Environment Detector** | Runs at startup; detects OS platform, GPU availability, camera backend API, and Bluetooth stack. Outputs an `env_profile` that Tool Packages use to select the correct implementation variant. See §9. |

#### Device Data Bus

The bus is the single entry point for all device data. It decouples transport protocol from Tool logic.

- **Poll path**: Scheduler triggers a poll cycle → Device Adapter fetches data → normalizes to bus message format → stored in ring buffer
- **Push path**: Device sends HTTP POST to local webhook endpoint → same normalization → same ring buffer
- MCP Tools read exclusively from the bus. They never call device SDKs directly.

#### MCP Tool Layer

All tools are registered as standard MCP tools (JSON Schema input/output). Tools are grouped into **Tool Packages**, each deployable as an independent process or module.

#### Storage

All persistence is local filesystem on the host PC. No external database required for MVP.

```
~/.clawtail/
├── data/
│   ├── frames/          # Raw captured image frames (JPEG)
│   ├── sensor_logs/     # Time-series sensor data (JSONL)
│   └── reports/         # Generated Markdown reports
├── summaries/           # AI-generated text summaries of frames/sensor data
├── tasks/               # User-defined Task JSON configs
└── logs/                # System and agent run logs
```

---

## 3. Three-Layer Model: Tools → Tasks → Agent

### 3.1 Tools (Atomic Capabilities)

Tools are the lowest-level primitives. Each tool does exactly one thing and has no knowledge of any specific monitoring scenario.

**Design rules for Tools**:
- Input/output must be serializable (JSON)
- Must not embed scenario-specific logic (e.g., "check if plant needs water")
- Must be stateless; state is managed by the Task Runner or persisted to storage
- All registered via MCP protocol

**Tool Package: `vision`**

| Tool Name | Description | Input | Output |
|---|---|---|---|
| `vision.capture_frame` | Capture a single frame from a camera source | `source_id`, `save_path?` | `frame_path`, `timestamp` |
| `vision.detect_objects` | Run object detection on an image (YOLOv8) | `frame_path`, `confidence?` | `[{label, confidence, bbox}]` |
| `vision.analyze_image` | Send image to vision LLM with a prompt | `frame_path`, `prompt` | `analysis_text` |
| `vision.compare_frames` | Compare two frames, describe differences | `frame_path_a`, `frame_path_b`, `prompt?` | `diff_description` |
| `vision.count_objects` | Count occurrences of a label in detection results | `detections`, `label` | `count` |

**Tool Package: `sensor`**

| Tool Name | Description | Input | Output |
|---|---|---|---|
| `sensor.list_devices` | List all registered sensor devices | — | `[{device_id, type, status}]` |
| `sensor.read_latest` | Read the latest value from a sensor | `device_id` | `{value, unit, timestamp}` |
| `sensor.read_history` | Read historical readings within a time range | `device_id`, `from`, `to` | `[{value, unit, timestamp}]` |
| `sensor.get_stats` | Compute statistics over a time range | `device_id`, `from`, `to` | `{min, max, avg, trend}` |

**Tool Package: `storage`**

| Tool Name | Description | Input | Output |
|---|---|---|---|
| `storage.save_summary` | Save a text summary with metadata | `content`, `category`, `tags?` | `summary_id`, `path` |
| `storage.read_summary` | Read a previously saved summary | `summary_id` | `content`, `metadata` |
| `storage.list_summaries` | List summaries by category/tag/time | `category?`, `tags?`, `from?`, `to?` | `[summary_metadata]` |
| `storage.save_report` | Save a Markdown report to disk | `content`, `title`, `task_id` | `report_path` |
| `storage.read_report` | Read a saved report | `report_path` | `content` |

**Tool Package: `notify`**

| Tool Name | Description | Input | Output |
|---|---|---|---|
| `notify.feishu_send` | Send a message to a Feishu webhook | `message`, `webhook_url?` | `success` |
| `notify.feishu_send_report` | Send a report summary + link to Feishu | `title`, `summary`, `report_path` | `success` |

**Tool Package: `knowledge`**

| Tool Name | Description | Input | Output |
|---|---|---|---|
| `knowledge.search_web` | Search the web for a query and return summarized results | `query`, `max_results?` | `[{title, snippet, url}]` |
| `knowledge.identify_plant` | Identify a plant species from an image using vision LLM | `frame_path` | `{species, common_name, confidence, care_summary}` |
| `knowledge.fetch_care_guide` | Fetch structured care guide for a known plant species | `species_name` | `{watering, light, temperature, humidity, notes}` |
| `knowledge.search_local_kb` | Search the local knowledge base (RAG over saved summaries and reports) | `query`, `category?` | `[{summary_id, relevance_score, snippet}]` |

> **Design note**: `knowledge.identify_plant` and `knowledge.fetch_care_guide` are intentionally generic — they identify *any* plant and fetch *any* care guide. They are not hardcoded for a specific plant. The LLM uses these tools to self-construct a care Task at runtime.

### 3.2 Tasks (User-Composable Workflows)

A Task is a JSON configuration file that defines:
1. **Trigger**: when the task runs
2. **Steps**: an ordered list of LLM instructions and tool hints
3. **Context policy**: what historical data to inject into LLM context
4. **Output policy**: what to save and what to notify

Tasks do NOT hardcode tool call sequences. They provide the LLM with a goal and constraints; the LLM decides which tools to call.

**Task JSON Schema (simplified)**:

```json
{
  "task_id": "string",
  "name": "string",
  "description": "string",
  "trigger": {
    "type": "cron | on_event | manual",
    "cron": "0 */30 * * * *",
    "event": "device.push | task.complete",
    "event_source": "task_id or device_id"
  },
  "context": {
    "include_summaries": {
      "category": "string",
      "last_n": 5
    },
    "include_sensor_stats": {
      "device_ids": ["string"],
      "window_minutes": 60
    }
  },
  "goal": "Natural language description of what the agent should accomplish",
  "constraints": [
    "Do not call vision.analyze_image more than 3 times per run",
    "Always save a summary before sending a notification"
  ],
  "output": {
    "save_report": true,
    "notify": {
      "feishu": true,
      "trigger": "always | on_anomaly | on_complete"
    }
  }
}
```

**LLM-assisted Task generation**: Users can describe a task in natural language via CLI. The LLM generates a Task JSON draft. The user reviews and edits the JSON before saving. The JSON schema is designed to be forward-compatible with a visual node editor (each step maps to a node, trigger maps to an entry node, output maps to exit nodes).

### 3.3 Agent (LLM Orchestration)

The Agent receives a Task's goal, constraints, and context, then autonomously calls MCP Tools to fulfill the goal. It operates in a ReAct-style loop (Reason → Act → Observe → Reason...) until the goal is satisfied or a step limit is reached.

**Context window budget policy**:
- System prompt + Task goal + constraints: ~1,000 tokens
- Injected summaries: max 2,000 tokens
- Injected sensor stats: max 500 tokens
- Tool call history (current run): max 3,000 tokens
- **Raw images**: never injected directly; referenced by path only
- **Raw time-series tables**: never injected; use `sensor.get_stats` output instead

#### Self-Planning Mode

For open-ended goals where no pre-authored Task JSON exists, the Agent operates in **Self-Planning Mode**:

```
1. Receive high-level goal (e.g., "Monitor and care for the plant on my desk")
2. Use knowledge.identify_plant → identify species
3. Use knowledge.fetch_care_guide → retrieve care requirements
4. Use knowledge.search_web → supplement with latest care advice if needed
5. Synthesize a Task workflow plan (which tools to call, at what frequency, what thresholds trigger alerts)
6. Persist the generated plan as a Task JSON for future scheduled runs
7. Execute the first run immediately
```

The generated Task JSON is saved to `~/.clawtail/tasks/` and can be reviewed or edited by the user. This mode bridges the gap between "I have no idea what tools to use" and "I have a fully configured Task JSON".

---

## 4. MVP Scope

### 4.1 Deliverables

| # | Deliverable | Description |
|---|---|---|
| 1 | **Device Data Bus** | Poll + Push hybrid, HTTP webhook for push, configurable poll interval |
| 2 | **MCP Tool Packages** | `vision`, `sensor`, `storage`, `notify` — all 4 packages functional |
| 3 | **LiteLLM Integration** | Multi-model abstraction, configurable model per task |
| 4 | **Task Runner** | JSON config loading, LLM orchestration loop, step limit enforcement |
| 5 | **Scheduler** | Cron and event-based triggers |
| 6 | **CLI** | Start/stop tasks, list tasks, view run logs, generate task from natural language |
| 7 | **Local Storage** | File-based persistence as specified in section 2.2 |
| 8 | **Feishu Notification** | Webhook-based push for summaries and reports |
| 9 | **Demo: Plant Watering Reminder** | See section 5.1 |
| 10 | **Demo: Chemistry Experiment Monitor** | See section 5.2 |
| 11 | **Demo: Drinking Water Reminder** | See section 5.3 |

### 4.2 Explicitly Out of Scope for MVP

- Web UI (planned for v0.2)
- Actuator / write-back to physical devices
- Multi-user / multi-PC deployment
- Cloud deployment
- Authentication / access control
- Mobile app

---

## 5. Demo Scenarios

### 5.1 Plant Watering Reminder

**Goal**: Monitor a potted plant via camera and soil moisture sensor. The Agent first identifies the plant species, retrieves its specific care requirements, then autonomously constructs and executes a monitoring workflow.

**Devices**: USB camera, soil moisture sensor (WiFi/BT connected)

**Self-Planning flow** (first run, no pre-authored Task JSON):
1. `knowledge.identify_plant` → e.g., "Monstera deliciosa"
2. `knowledge.fetch_care_guide` → watering frequency, soil moisture threshold, light requirements
3. `knowledge.search_web` → supplement with current best practices
4. LLM synthesizes a Task JSON and saves it to `~/.clawtail/tasks/plant_monitor_auto.json`
5. Task executes immediately and on the generated schedule

**Generated Task design** (example output of Self-Planning):
- Trigger: cron, every 2 hours
- Agent goal: "Assess the current health and hydration status of the plant. Check both visual appearance and soil moisture data against the care guide for this species. If watering is needed, send a Feishu alert. Always save a summary."
- The Agent calls: `vision.capture_frame` → `vision.analyze_image` → `sensor.read_latest` (soil moisture) → `sensor.get_stats` (trend) → `storage.search_local_kb` (past summaries) → `storage.save_summary` → conditionally `notify.feishu_send`
- **The Task JSON does NOT specify this call sequence.** The LLM derives it from the goal and care guide context.

**Key constraint**: `vision.analyze_image` prompt must be generic ("describe the plant's visual health indicators") not task-specific ("does this plant need water").

### 5.2 Chemistry Experiment Monitor

**Goal**: Monitor a chemistry experiment overnight. Detect visual changes in the reaction vessel. Generate a structured experiment log at the end.

**Devices**: USB camera (fixed mount over experiment setup)

**Task design**:
- Trigger: cron, every 15 minutes during experiment window
- Agent goal: "Capture the current state of the experiment. Compare with the previous frame. Describe any observable changes (color, precipitate, gas bubbles, volume change). Save a timestamped summary. If significant change is detected, send an immediate Feishu alert."
- End-of-experiment trigger: manual or scheduled `on_task_complete` → generate full Markdown report from all summaries

**Report structure** (generated by LLM from summaries):
```
# Experiment Log — [date]
## Timeline
| Time | Observation |
|------|-------------|
| ...  | ...         |
## Key Events
## Conclusion
```

### 5.3 Drinking Water Reminder

**Goal**: Monitor a person's water drinking frequency via camera. Send a health reminder if no drinking action is detected within a configurable time window.

**Devices**: USB camera (desk-facing)

**Detection strategy**:

This scenario uses a two-tier detection architecture to minimize both API cost and CPU load:

```
┌─────────────────────────────────────────────────────────┐
│  Tier 1: Background Watcher (Local Model, always-on)    │
│  YOLOv8-nano, 1 frame / 30 seconds                      │
│  Detects: drinking vessel near face/mouth region        │
│  On detection: log event → sleep 5 minutes (cooldown)   │
│  No LLM involved at this tier                           │
└─────────────────────────┬───────────────────────────────┘
                          │ aggregated event log
┌─────────────────────────▼───────────────────────────────┐
│  Tier 2: LLM Summarizer (scheduled, every 90 minutes)   │
│  Agent reads event log for the past 90 minutes          │
│  Reasons over drinking frequency vs. health baseline    │
│  Sends Feishu reminder if frequency is insufficient     │
│  Saves daily summary                                    │
└─────────────────────────────────────────────────────────┘
```

**Rationale for parameters**:
- **30-second sampling**: A drinking action lasts ≥15 seconds; 30-second interval guarantees at least one frame captures the action while keeping CPU usage negligible
- **5-minute cooldown after detection**: Prevents duplicate logging of a single drinking session; one drinking event typically completes within 5 minutes
- **90-minute LLM summary window**: Aligns with recommended hydration check intervals; reduces LLM API calls to ~10 per day

**Tool usage**:
- `vision.start_watch`: Start the background watcher with specified device, model, label filter, interval, and cooldown parameters
- `vision.detect_objects`: Called internally by the watcher per frame
- `vision.count_objects`: Aggregates detection events over a time window
- `storage.save_summary`: Persists the LLM's 90-minute assessment
- `notify.feishu_send`: Sends reminder if needed

**Task design**:
- **Watcher Task**: Trigger on system startup (`on_event: system.start`); runs `vision.start_watch` as a persistent background process
- **Summarizer Task**: Trigger cron every 90 minutes; Agent goal: "Review the drinking activity log for the past 90 minutes. Compare against a healthy hydration baseline (at least 1 drink per 90 minutes). If insufficient, send a Feishu hydration reminder. Save a daily summary."
- The heavy lifting (frame sampling, object detection, cooldown management) is done entirely by the local model watcher. The LLM only reasons over the aggregated event count.

---

## 6. Technical Stack

| Layer | Technology | Rationale |
|---|---|---|
| Agent Orchestration | Python | Rich LLM/ML ecosystem, easy to extend |
| MCP Tool Servers | Python (primary), extensible to any language | MCP is language-agnostic; Python for ML tools |
| LLM Abstraction | LiteLLM | Unified API for OpenAI, Anthropic, Gemini, local models |
| Local Vision Model | YOLOv8-nano (Ultralytics) | Lightweight, CPU-capable, well-documented |
| Device Data Bus | Python asyncio + HTTP (FastAPI webhook) | Simple, low-dependency |
| Task Config | JSON (with JSON Schema validation) | Human-readable, forward-compatible with visual editor |
| Storage | Local filesystem (JSONL, JPEG, Markdown) | Zero infrastructure dependency |
| Notification | Feishu Incoming Webhook | As specified |
| CLI | Python Click or Typer | Ergonomic, well-maintained |
| MCP Protocol | `mcp` Python SDK (official) | Standard compliance |
| Environment Detection | Python `platform`, `torch`, `cv2` capability probes | Auto-selects tool variants at startup |

---

## 7. Repository Structure

```
clawtail/
├── core/
│   ├── agent/              # LLM orchestration loop, ReAct engine
│   ├── scheduler/          # Cron + event trigger management
│   ├── task_runner/        # Task JSON loader and executor
│   └── bus/                # Device Data Bus (poll + push)
├── tools/
│   ├── vision/             # MCP Tool Package: vision
│   ├── sensor/             # MCP Tool Package: sensor
│   ├── storage/            # MCP Tool Package: storage
│   ├── notify/             # MCP Tool Package: notify
│   └── knowledge/          # MCP Tool Package: knowledge (web search, plant ID, RAG)
├── adapters/
│   ├── camera/             # Camera device adapters (USB, IP)
│   │   ├── v4l2.py         # Linux V4L2 backend
│   │   ├── directshow.py   # Windows DirectShow backend
│   │   └── avfoundation.py # macOS AVFoundation backend
│   └── sensor/             # Sensor device adapters (ESP32, RPi GPIO, BT)
├── env/
│   ├── detector.py         # Environment Detector: OS, GPU, camera API, BT stack
│   └── profiles/           # Pre-defined env profiles (linux-cpu, win-gpu, macos-cpu, ...)
├── tasks/
│   └── examples/           # Example Task JSON configs for 3 demos
├── cli/
│   └── main.py             # CLI entry point
├── config/
│   ├── config.yaml         # Global config (LLM model, Feishu webhook, etc.)
│   └── devices.yaml        # Registered device definitions
├── tests/
└── docs/
    ├── General_analysis.md
    ├── plan-01.md
    └── spec.md
```

---

## 8. Device Integration Protocol

### 8.1 Device Registration

Devices are registered in `config/devices.yaml`:

```yaml
devices:
  - id: "desk_camera"
    type: "camera"
    transport: "usb"
    source: "/dev/video0"   # or RTSP URL for IP camera

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

### 8.2 Data Bus Message Format

All device data, regardless of transport, is normalized to:

```json
{
  "device_id": "string",
  "device_type": "camera | sensor",
  "timestamp": "ISO8601",
  "payload": {
    "type": "frame | reading",
    "data": "base64_image_or_numeric_value",
    "unit": "string (for sensors)",
    "meta": {}
  }
}
```

---

## 9. Environment Detection & Tool Variant Selection

### 9.1 Detection Targets

On every startup, the Environment Detector probes the host system and produces an `env_profile`:

```json
{
  "os": "linux | windows | macos",
  "camera_backend": "v4l2 | directshow | avfoundation | none",
  "gpu_available": true,
  "gpu_type": "cuda | mps | none",
  "bluetooth_available": true,
  "python_version": "3.11.x",
  "detected_cameras": [{"id": "0", "name": "USB Camera"}],
  "detected_serial_ports": ["/dev/ttyUSB0"]
}
```

### 9.2 Tool Variant Selection Rules

| Condition | Selected Variant |
|---|---|
| `os == linux` | Camera adapter: `v4l2` |
| `os == windows` | Camera adapter: `directshow` |
| `os == macos` | Camera adapter: `avfoundation` |
| `gpu_available == true, gpu_type == cuda` | YOLO model: `yolov8s` (small, GPU) |
| `gpu_available == true, gpu_type == mps` | YOLO model: `yolov8s` (MPS, Apple Silicon) |
| `gpu_available == false` | YOLO model: `yolov8n` (nano, CPU-only) |
| `bluetooth_available == false` | BT sensor adapters disabled; warn user |

### 9.3 Tool Package Declaration

Each Tool Package declares its variants in a `variants.yaml`:

```yaml
# tools/vision/variants.yaml
variants:
  - id: "yolo_cuda"
    requires: {gpu_type: "cuda"}
    impl: "vision_yolo_gpu.py"
  - id: "yolo_mps"
    requires: {gpu_type: "mps"}
    impl: "vision_yolo_mps.py"
  - id: "yolo_cpu"
    requires: {}   # fallback, always available
    impl: "vision_yolo_cpu.py"
```

The Environment Detector selects the first matching variant at startup. Users can override via `config.yaml`:

```yaml
tool_variant_overrides:
  vision.yolo: "yolo_cpu"   # force CPU even if GPU is available
```

---

## 10. Phased Roadmap

### Phase 1 — MVP (v0.1)
- All items in section 4.1
- Target: CLI works end-to-end for all 3 demo scenarios
- Hardware: USB camera + 1 WiFi sensor (soil moisture or temperature)

### Phase 2 — Hardening (v0.2)
- Web UI for Task management and monitoring dashboard
- LLM-assisted Task generation via CLI (`clawtail task generate "..."`)
- Multi-camera support
- Improved context summarization (rolling summary compression)
- Unit and integration test coverage ≥ 60%

### Phase 3 — Ecosystem (v0.3+)
- Tool Package registry (community-contributed tool packages)
- Visual Task editor (node-based, JSON-compatible)
- Additional notification channels (email, WeChat Work)
- IoT security research integration (as planned)
- Plugin SDK documentation for third-party Tool Package authors

---

## 11. Open Questions (To Be Resolved)

| # | Question | Owner | Target Phase |
|---|---|---|---|
| Q1 | Final project name (ClawWithTail placeholder) | Product | Pre-v0.1 |
| Q2 | Minimum supported OS: Environment Detector targets Linux + macOS + Windows; confirm priority order | Infra | Pre-v0.1 |
| Q3 | YOLOv8 model weight distribution (bundle vs. download on first run) | ML | v0.1 |
| Q4 | Feishu webhook config: single global or per-task override? | Backend | v0.1 |
| Q5 | Task JSON versioning strategy for backward compatibility | Backend | v0.2 |
| Q6 | Visual Task editor: build custom or embed existing (e.g., React Flow) | Frontend | v0.3 |
| Q7 | `knowledge.search_web` provider: Tavily API, SerpAPI, or self-hosted Searxng? | Backend | v0.1 |
| Q8 | `vision.start_watch` background process management: subprocess, asyncio task, or OS service? | Backend | v0.1 |
