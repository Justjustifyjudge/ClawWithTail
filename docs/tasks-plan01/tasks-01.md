# Tasks-01 — Sprint 0: Foundation

> **Source**: plan-01.md §6 Sprint 0 + §2 Data Models + §8 Configuration Reference
> **Sprint**: Sprint 0 (Week 1–2)
> **Goal**: 项目脚手架、配置加载、数据模型、环境检测全部就绪，后续所有模块可直接 import 使用

---

## T01 — 初始化项目仓库与 Python 包结构

**对应**: plan-01.md S0-1

**执行步骤**:
1. 在项目根目录创建 `pyproject.toml`，使用 `[build-system]` 为 `hatchling`，Python 要求 `>=3.11`
2. 声明项目依赖（初始集合）：`litellm`, `mcp`, `fastapi`, `uvicorn`, `apscheduler`, `typer`, `pydantic`, `httpx`, `opencv-python`, `ultralytics`, `bleak`, `pyserial`, `python-slugify`, `tavily-python`
3. 创建以下空包目录（每个目录含 `__init__.py`）：
   - `core/agent/`, `core/bus/`, `core/scheduler/`, `core/task_runner/`, `core/config/`, `core/models/`
   - `tools/vision/`, `tools/sensor/`, `tools/storage/`, `tools/notify/`, `tools/knowledge/`
   - `adapters/camera/`, `adapters/sensor/`
   - `env/`, `env/profiles/`
   - `cli/`
   - `tasks/examples/`
   - `tests/unit/`, `tests/integration/`
4. 创建 `.env.example` 文件，包含所有需要的环境变量占位符：`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `FEISHU_WEBHOOK_URL`, `TAVILY_API_KEY`
5. 创建 `.gitignore`，忽略 `.env`, `~/.clawtail/`, `__pycache__/`, `*.pyc`, `.venv/`

**验收标准**: 执行 `python -m clawtail --help` 不报 ImportError（即使命令本身尚未实现）

---

## T02 — 实现 `config.yaml` 与 `devices.yaml` 的 Pydantic 配置加载器

**对应**: plan-01.md S0-2 + §8 Configuration Reference

**执行步骤**:
1. 创建 `config/config.yaml`，内容严格按照 plan-01.md §8 的示例，所有敏感值使用 `${ENV_VAR}` 占位符
2. 创建 `config/devices.yaml`，包含三个示例设备：`desk_camera`（usb）、`plant_soil_sensor`（wifi_poll）、`lab_temp_sensor`（wifi_push）
3. 在 `core/config/models.py` 中用 Pydantic v2 定义以下模型：
   - `LLMConfig`（default_model, vision_model, fallback_model, api_keys）
   - `NotifyConfig`（feishu_default_webhook）
   - `KnowledgeConfig`（search_provider, tavily_api_key）
   - `BusConfig`（webhook_port=17171, ring_buffer_size=1000）
   - `StorageConfig`（base_dir="~/.clawtail"）
   - `AppConfig`（组合以上所有）
   - `DeviceConfig`（id, type, transport, source?, poll_url?, poll_interval_seconds?, push_webhook_path?, subtype?）
   - `DevicesConfig`（devices: list[DeviceConfig]）
4. 在 `core/config/loader.py` 中实现 `load_app_config(path) -> AppConfig` 和 `load_devices_config(path) -> DevicesConfig`，支持 `${ENV_VAR}` 环境变量替换
5. 在 `core/config/__init__.py` 中暴露全局单例 `app_config` 和 `devices_config`，在首次 import 时自动从默认路径加载

**验收标准**: `from core.config import app_config; print(app_config.bus.webhook_port)` 输出 `17171`

---

## T03 — 定义全局共享数据模型

**对应**: plan-01.md §2 Data Models & Interface Contracts

**执行步骤**:
1. 在 `core/models/env_profile.py` 中定义 `EnvProfile` dataclass，字段完全按照 plan-01.md §2.1
2. 在 `core/models/bus.py` 中定义 `BusPayload` 和 `BusMessage` dataclass，字段完全按照 plan-01.md §2.2；添加 `to_dict()` 和 `from_dict()` 方法用于 JSONL 序列化
3. 在 `core/models/task.py` 中定义以下 dataclass：`TriggerConfig`, `SummaryContextConfig`, `SensorStatsContextConfig`, `ContextConfig`, `OutputConfig`, `TaskConfig`，字段完全按照 plan-01.md §2.3
4. 在 `core/models/agent.py` 中定义 `ToolCallRecord`（tool_name, input_args, output, duration_ms）和 `AgentRunResult` dataclass，字段完全按照 plan-01.md §2.4
5. 在 `core/models/__init__.py` 中统一 re-export 所有模型
6. 为每个模型编写 `tests/unit/test_models.py`，验证 `to_dict()` / `from_dict()` 往返序列化正确

**验收标准**: `from core.models import BusMessage, TaskConfig, AgentRunResult` 无报错；序列化测试全部通过

---

## T04 — 实现本地存储目录初始化

**对应**: plan-01.md S0-5 + spec.md §2.2 Storage

**执行步骤**:
1. 在 `core/storage_init.py` 中实现 `init_storage(base_dir: str = "~/.clawtail") -> Path` 函数
2. 函数需创建以下目录树（如已存在则跳过）：
   ```
   ~/.clawtail/
   ├── data/frames/
   ├── data/sensor_logs/
   ├── data/reports/
   ├── summaries/
   ├── tasks/
   ├── logs/runs/
   ├── models/
   └── cache/care_guides/
   ```
3. 在 `~/.clawtail/` 下创建 `.clawtail_version` 文件，写入当前版本号（`0.1.0`）
4. 函数返回 `base_dir` 的 `Path` 对象
5. 在系统启动流程中（`cli/main.py` 的 `start` 命令）调用此函数作为第一步

**验收标准**: 调用 `init_storage()` 后，`~/.clawtail/data/frames/` 目录存在；重复调用不报错

---

## T05 — 实现环境检测器 `env/detector.py`

**对应**: plan-01.md S0-3 + §3.1 M-ENV

**执行步骤**:
1. 在 `env/detector.py` 中实现以下私有函数：
   - `_detect_os() -> Literal["linux", "windows", "macos"]`：使用 `platform.system()` 映射
   - `_detect_gpu() -> Literal["cuda", "mps", "none"]`：try/except import torch，分别检测 CUDA 和 MPS
   - `_detect_camera_backend(os_name) -> Literal["v4l2", "directshow", "avfoundation", "none"]`：按 OS 映射，并用 `cv2.VideoCapture(0)` 探测是否可用
   - `_detect_bluetooth() -> bool`：try import bleak，catch ImportError 返回 False
   - `_enumerate_cameras() -> list[dict]`：尝试索引 0-4，返回可用摄像头列表
   - `_enumerate_serial_ports() -> list[str]`：使用 `serial.tools.list_ports.comports()`
   - `_resolve_yolo_variant(gpu_type) -> Literal["yolov8n", "yolov8s"]`：有 GPU 返回 s，否则 n
2. 实现公开函数 `detect() -> EnvProfile`，按 plan-01.md §3.1 骨架组合调用上述私有函数
3. 在 `env/state.py` 中实现单例：`_profile: EnvProfile | None = None`，`get_env_profile() -> EnvProfile`（懒加载，首次调用时执行 `detect()`）
4. 所有探测失败时记录 `logging.warning`，不抛出异常
5. 支持 `config.yaml` 中 `tool_variant_overrides.vision.yolo` 覆盖 `yolo_variant`

**验收标准**: `from env.state import get_env_profile; p = get_env_profile(); print(p.os)` 输出当前 OS 名称；在无摄像头环境下不崩溃

---

## T06 — 实现 `env/profiles/` 预定义环境 Profile 与变体选择规则

**对应**: plan-01.md §3.1 + spec.md §9.2 Tool Variant Selection Rules

**执行步骤**:
1. 在 `env/profiles/` 下创建 4 个 YAML 文件：`linux-cpu.yaml`, `linux-gpu-cuda.yaml`, `macos-cpu.yaml`, `win-cpu.yaml`，每个文件描述该环境下的预期 `env_profile` 字段值（用于测试 mock）
2. 在 `env/variant_selector.py` 中实现 `select_camera_adapter(profile: EnvProfile) -> str` 函数，按 spec.md §9.2 规则返回适配器类名：`V4L2CameraAdapter` / `DirectShowCameraAdapter` / `AVFoundationCameraAdapter`
3. 实现 `select_yolo_variant(profile: EnvProfile) -> str` 函数，返回 `"yolov8n"` 或 `"yolov8s"`
4. 在 `tools/vision/variants.yaml` 中按 spec.md §9.3 格式声明三个变体：`yolo_cuda`, `yolo_mps`, `yolo_cpu`
5. 编写 `tests/unit/test_variant_selector.py`，覆盖所有 OS × GPU 组合（6 个测试用例）

**验收标准**: 6 个变体选择测试用例全部通过

---

## T07 — 实现 Task JSON Schema 与验证器

**对应**: plan-01.md S3-3 + spec.md §3.2

**执行步骤**:
1. 在 `core/task_runner/schema.json` 中编写完整的 JSON Schema（draft-07），覆盖 spec.md §3.2 中 Task JSON 的所有字段，包括：
   - `task_id`（string, required）
   - `schema_version`（string, required, enum: ["1.0"]）
   - `name`, `description`（string, required）
   - `trigger`（object，type 为 enum: cron/on_event/manual，条件必填 cron/event/event_source）
   - `context`（object，可选，含 include_summaries 和 include_sensor_stats）
   - `goal`（string, required）
   - `constraints`（array of string, optional）
   - `max_steps`（integer, default 20）
   - `output`（object，含 save_report, notify）
2. 在 `core/task_runner/validator.py` 中实现 `validate_task(task_dict: dict) -> tuple[bool, list[str]]`，使用 `jsonschema` 库验证，返回 (is_valid, error_messages)
3. 在 `core/task_runner/loader.py` 中实现 `load_task(path: str) -> TaskConfig`，读取 JSON 文件 → 验证 → 转换为 `TaskConfig` dataclass
4. 在 `tasks/examples/` 下创建三个示例 Task JSON 文件：`plant_monitor.json`, `chemistry_monitor.json`, `drinking_watcher.json`，内容对应 plan-01.md §5 的三个 Demo 场景
5. 编写 `tests/unit/test_task_loader.py`，测试：合法 Task JSON 加载成功；缺少 required 字段时返回错误；trigger.type=cron 但缺少 cron 字段时返回错误

**验收标准**: 三个示例 Task JSON 验证通过；非法 Task JSON 返回明确错误信息

---

## T08 — 实现 CLI 框架与 `clawtail env` 命令组

**对应**: plan-01.md S0-1 + §3.9 M-CLI（env 命令部分）

**执行步骤**:
1. 在 `cli/main.py` 中使用 Typer 创建主 app：`app = typer.Typer(name="clawtail", help="ClawWithTail — Physical World AI Agent")`
2. 创建子命令组：`env_app = typer.Typer()`，注册到主 app：`app.add_typer(env_app, name="env")`
3. 实现 `clawtail env show` 命令：调用 `get_env_profile()`，用 `rich.table.Table` 格式化输出所有字段
4. 实现 `clawtail env check` 命令：强制重新运行 `detect()`（清除单例缓存），输出新的 env_profile
5. 在 `cli/main.py` 中添加入口：`if __name__ == "__main__": app()`
6. 在 `pyproject.toml` 中注册 CLI 入口点：`[project.scripts] clawtail = "cli.main:app"`

**验收标准**: `clawtail env show` 输出包含 os、camera_backend、gpu_type、yolo_variant 字段的表格；`clawtail env check` 重新检测并输出

---

## T09 — 编写 Sprint 0 集成冒烟测试

**对应**: plan-01.md §7 Testing Strategy（Sprint 0 范围）

**执行步骤**:
1. 在 `tests/unit/test_config_loader.py` 中编写测试：
   - 加载 `config/config.yaml` 成功，`app_config.bus.webhook_port == 17171`
   - 加载 `config/devices.yaml` 成功，`devices_config.devices` 长度为 3
   - `${ENV_VAR}` 占位符在环境变量存在时被正确替换
2. 在 `tests/unit/test_storage_init.py` 中编写测试：
   - `init_storage(tmp_path)` 创建所有必要子目录
   - 重复调用不抛出异常
3. 在 `tests/unit/test_env_detector.py` 中编写测试（使用 `unittest.mock.patch`）：
   - mock `platform.system()` 返回 "Linux" → `env_profile.os == "linux"`
   - mock `torch.cuda.is_available()` 返回 True → `env_profile.gpu_type == "cuda"`, `yolo_variant == "yolov8s"`
   - mock `cv2.VideoCapture` 抛出异常 → `camera_backend == "none"`，不崩溃
4. 确保所有测试可通过 `pytest tests/unit/` 一键运行

**验收标准**: `pytest tests/unit/` 全部通过，无 skip，无 error
