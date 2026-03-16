# ClawWithTail 🐾

> **A Physical World AI Agent Platform** — connects large language model APIs to cameras and IoT sensors, enabling autonomous monitoring, analysis, and notification workflows.

ClawWithTail bridges the gap between the digital and physical world. It runs on your local machine, reads from cameras and sensors, reasons with LLMs via a ReAct loop, and sends actionable alerts to Feishu — all driven by declarative Task JSON files.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ClawWithTail                             │
│                                                                 │
│  ┌──────────┐   ┌──────────────────────────────────────────┐   │
│  │  CLI     │   │           Agent Layer                    │   │
│  │clawtail  │──▶│  ReactLoop → ContextBudget → LLMEngine   │   │
│  └──────────┘   │  TaskRunner → TaskScheduler              │   │
│                 │  SelfPlanner (Self-Planning Mode)         │   │
│                 └──────────────┬─────────────────────────┘   │
│                                │ MCP Tool Protocol             │
│  ┌─────────────────────────────▼─────────────────────────┐   │
│  │                  MCP Tool Layer                        │   │
│  │  vision | sensor | storage | notify | knowledge        │   │
│  └─────────────────────────────┬─────────────────────────┘   │
│                                │                               │
│  ┌─────────────────────────────▼─────────────────────────┐   │
│  │                  Device Layer (Bus)                    │   │
│  │  CameraAdapter | SensorAdapter | Bus | PollManager     │   │
│  │  WebhookServer (push) | PollManager (pull)             │   │
│  └─────────────────────────────┬─────────────────────────┘   │
│                                │                               │
│              Camera / Sensors / IoT Devices                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Step 1 — Clone and install

```bash
git clone https://github.com/your-org/clawtail.git
cd clawtail
pip install -e .
```

### Step 2 — Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in:
#   OPENAI_API_KEY=sk-...
#   FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/...
#   TAVILY_API_KEY=tvly-...  (optional, for web search)
```

### Step 3 — Register your devices

```bash
# Edit config/devices.yaml to add your camera and sensors:
#
# devices:
#   - device_id: desk_camera
#     type: camera
#     source_id: 0          # OpenCV camera index
#
#   - device_id: plant_soil_sensor
#     type: sensor
#     protocol: wifi_poll
#     poll_url: http://192.168.1.100/sensor
#     poll_interval_seconds: 60
```

### Step 4 — Verify your environment

```bash
clawtail env check
# Expected output: table showing os/camera_backend/gpu_type/yolo_variant
```

### Step 5 — Start the daemon

```bash
clawtail start
# Expected: ✅ ClawWithTail started. Press Ctrl+C to stop.
```

---

## Demo Scenarios

### 🌱 Plant Watering Reminder

Monitors your desk plant every 2 hours. Checks visual health and soil moisture. Sends a Feishu alert when watering is needed.

```bash
# Run immediately (without waiting for cron)
clawtail task run plant_monitor

# Or let the scheduler handle it automatically after clawtail start
```

### 🧪 Chemistry Experiment Monitor

Captures the experiment state every 15 minutes. Detects significant changes (color, precipitate, gas). Sends immediate Feishu alerts on anomalies. Generates a full Markdown report at the end.

```bash
clawtail task run chemistry_monitor

# Generate experiment report
clawtail task run chemistry_report
```

### 💧 Drinking Water Reminder

Starts a background watcher on system startup. Counts drinking events every 90 minutes. Sends a Feishu reminder if you haven't drunk enough water.

```bash
# Watcher starts automatically on clawtail start
# Or trigger manually:
clawtail task run drinking_summarizer
```

---

## Adding a New Task

### Option A — Write a Task JSON manually

Create `~/.clawtail/tasks/my_task.json`:

```json
{
  "task_id": "my_task",
  "schema_version": "1.0",
  "name": "My Custom Task",
  "description": "What this task does",
  "trigger": {
    "type": "cron",
    "cron": "0 */4 * * *"
  },
  "goal": "Describe what the agent should accomplish each run.",
  "constraints": [
    "Always save a summary",
    "Do not call notify more than once per run"
  ],
  "max_steps": 15,
  "context": {
    "include_summaries": {"category": "my_task", "last_n": 3}
  },
  "output": {
    "save_report": true,
    "notify_feishu": true,
    "notify_trigger": "on_anomaly"
  }
}
```

Validate it:

```bash
clawtail task validate ~/.clawtail/tasks/my_task.json
# ✅ Valid
```

### Option B — Use Self-Planning Mode (LLM generates the Task)

```bash
clawtail task generate "Monitor the aquarium temperature and alert me if it goes above 28°C"
# LLM generates and saves a TaskConfig JSON automatically
```

---

## CLI Reference

```
clawtail start                          Start the daemon
clawtail stop                           Stop the daemon
clawtail env show                       Show detected environment
clawtail env check                      Re-detect environment

clawtail device list                    List all configured devices
clawtail device test <device_id>        Test a device (capture/read)

clawtail task list                      List all configured tasks
clawtail task run <task_id>             Manually trigger a task
clawtail task show <task_id>            Show task configuration
clawtail task validate <path>           Validate a Task JSON file
clawtail task generate "<goal>"         Generate a task with LLM

clawtail log list                       List recent task runs
clawtail log show <run_id>              Show full run details
```

---

## Configuration

All configuration lives in `config/config.yaml`. Key sections:

| Section | Description |
|---|---|
| `llm` | LLM provider, model, API key env var |
| `bus.webhook_port` | Port for sensor push webhooks (default: 17171) |
| `storage.base_dir` | Data directory (default: `~/.clawtail`) |
| `notify.feishu_webhook_url` | Feishu bot webhook URL |
| `knowledge.tavily_api_key_env` | Env var name for Tavily API key |

---

## Requirements

- Python 3.11+
- OpenCV (`pip install opencv-python-headless`)
- An LLM API key (OpenAI, Anthropic, or any LiteLLM-compatible provider)
- Optional: Feishu bot webhook for notifications
- Optional: Tavily API key for web search in knowledge tools

---

## License

GPL-3.0 — see [LICENSE](LICENSE) for details.
