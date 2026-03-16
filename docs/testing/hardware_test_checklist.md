# Hardware-in-the-Loop Test Checklist

> **Project**: ClawWithTail  
> **Version**: 1.0.0  
> **Purpose**: Manual hardware validation before MVP release  
> **Instructions**: Fill in "Actual Result" and "Pass/Fail/Skip" for each item. Run on at least one real OS environment.

---

## Test Environment

| Field | Value |
|---|---|
| Test Date | ________ |
| Tester | ________ |
| OS | ☐ Windows 11  ☐ Ubuntu 22.04  ☐ macOS 14 |
| Python Version | ________ |
| GPU | ☐ NVIDIA (CUDA)  ☐ Apple Silicon (MPS)  ☐ CPU only |
| Camera Model | ________ |
| Sensor Hardware | ☐ ESP32 WiFi  ☐ Arduino Serial  ☐ BLE  ☐ None |

---

## 1. Camera Tests

### 1.1 Camera Detection

| OS | Command | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| Linux | `clawtail device list` | Table shows `desk_camera` with `V4L2` backend | | |
| Windows | `clawtail device list` | Table shows `desk_camera` with `DirectShow` backend | | |
| macOS | `clawtail device list` | Table shows `desk_camera` with `AVFoundation` backend | | |

### 1.2 Camera Capture

| Test | Command | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| Single frame capture | `clawtail device test desk_camera` | Outputs JPEG path; file size > 10 KB | | |
| JPEG validity | `python -c "import cv2; img=cv2.imread('<path>'); print(img.shape)"` | Prints `(H, W, 3)` — non-None | | |
| Mock camera (no hardware) | `CLAWTAIL_MOCK_CAMERA=1 clawtail device test desk_camera` | Outputs mock JPEG path; file exists | | |

---

## 2. Sensor Tests

### 2.1 WiFi Poll Sensor (ESP32)

| Test | Command | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| ESP32 mock server | Start `python tests/fixtures/esp32_mock_server.py` | Server running on port 8080 | | |
| Sensor poll | `clawtail device test plant_soil_sensor` | Outputs `{"value": <float>, "unit": "percent"}` | | |
| Bus message stored | `python -c "from core.bus import bus; print(bus.get_latest('plant_soil_sensor'))"` | Returns BusMessage with value | | |

### 2.2 Serial Sensor (Arduino)

| Test | Command | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| Serial port detection | `clawtail device list` | Shows serial port in device table | | |
| Serial read | `clawtail device test <serial_device_id>` | Outputs sensor value | | |

---

## 3. Feishu Webhook Test

| Test | Steps | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| Manual send | `python -c "import asyncio; from tools.notify.server import _feishu_send; asyncio.run(_feishu_send('Test message from ClawWithTail'))"` | Feishu group receives "Test message from ClawWithTail" | | |
| Report send | `python -c "import asyncio; from tools.notify.server import _feishu_send_report; asyncio.run(_feishu_send_report('Test Report', 'Summary text', '/tmp/test.md'))"` | Feishu group receives report notification | | |

---

## 4. YOLO Model Tests

### 4.1 First-Time Download

| Test | Steps | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| Auto-download | 1. Delete `~/.clawtail/models/` 2. Run `clawtail device test desk_camera` then trigger `vision.detect_objects` | Model downloads automatically to `~/.clawtail/models/`; detection runs | | |
| Cache hit | Run `vision.detect_objects` again | No download; uses cached model; faster startup | | |
| Variant selection | Check `clawtail env show` → `yolo_variant` field | Matches expected variant for hardware (n/s/m/l) | | |

---

## 5. Plant Watering Demo (Full End-to-End)

**Prerequisites**: Real camera connected, ESP32 soil sensor connected, Feishu webhook configured in `.env`

| Step | Action | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| 1 | `clawtail env check` | All devices detected; no errors | | |
| 2 | `clawtail start` | "✅ ClawWithTail started" printed | | |
| 3 | Wait for cron trigger (or `clawtail task run plant_monitor`) | Task starts; tool calls printed | | |
| 4 | Observe tool calls | `vision.capture_frame` → `vision.analyze_image` → `sensor.read_latest` → final answer | | |
| 5 | Check Feishu (if soil < 30%) | Feishu group receives watering alert | | |
| 6 | Check `~/.clawtail/logs/runs/plant_monitor/` | JSON run log file created | | |

---

## 6. Drinking Water Reminder Demo (Full End-to-End)

**Prerequisites**: Real camera at desk, Feishu webhook configured

| Step | Action | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| 1 | `clawtail start` | "✅ ClawWithTail started"; watcher auto-starts | | |
| 2 | Drink water in front of camera | Event logged to `~/.clawtail/data/drink_events.jsonl` | | |
| 3 | Wait 90 minutes (or manually trigger `clawtail task run drinking_summarizer`) | Summarizer runs | | |
| 4 | Adequate hydration scenario | Feishu NOT notified; summary saved | | |
| 5 | Insufficient hydration scenario (don't drink for 90 min) | Feishu receives 💧 reminder | | |

---

## 7. Chemistry Experiment Demo (Full End-to-End)

**Prerequisites**: Camera pointed at experiment setup, Feishu webhook configured

| Step | Action | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| 1 | `clawtail start` | Scheduler loaded with chemistry_monitor task | | |
| 2 | Wait 15 minutes (or `clawtail task run chemistry_monitor`) | Task runs; compare_frames called | | |
| 3 | Introduce visible change (add colored liquid) | Feishu alert sent; summary saved | | |
| 4 | Run report task | `clawtail task run chemistry_report` → Markdown report in `~/.clawtail/data/reports/` | | |
| 5 | Verify report | Report contains "Timeline" section | | |

---

## 8. Self-Planning Mode Test

| Test | Command | Expected Result | Actual Result | Pass/Fail/Skip |
|---|---|---|---|---|
| Generate plant task | `clawtail task generate "Monitor and care for the plant on my desk"` | TaskConfig JSON saved to `~/.clawtail/tasks/`; passes schema validation | | |
| Validate generated task | `clawtail task validate ~/.clawtail/tasks/<generated_id>.json` | "✅ Valid" | | |
| Run generated task | `clawtail task run <generated_id>` | Task executes; result logged | | |

---

## 9. Known Issues / Bugs Found

| # | Description | Severity | Status |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |

---

## Sign-off

| Role | Name | Signature | Date |
|---|---|---|---|
| IoT Engineer | | | |
| LLM Engineer | | | |
| QA | | | |
