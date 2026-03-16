# Tasks-02 — Sprint 1: Device Layer

> **Source**: plan-01.md §6 Sprint 1 + §3.2 M-BUS + §3.3 M-ADAPT-CAM + §3.4 M-ADAPT-SEN
> **Sprint**: Sprint 1 (Week 3–4)
> **Goal**: 设备数据总线、摄像头适配器、传感器适配器全部就绪，`clawtail device` 命令可用

---

## T10 — 实现摄像头适配器基类与三平台实现

**对应**: plan-01.md S1-1 + §3.3 M-ADAPT-CAM

**执行步骤**:
1. 在 `adapters/camera/base.py` 中定义抽象基类 `CameraAdapter`，包含：
   - `__init__(self, device_config: DeviceConfig, env_profile: EnvProfile)`
   - 抽象方法 `capture_frame(self, save_path: str) -> str`：保存 JPEG 到 save_path，返回实际路径
   - 抽象方法 `is_available(self) -> bool`
2. 在 `adapters/camera/v4l2.py` 中实现 `V4L2CameraAdapter`（Linux）：
   - 使用 `cv2.VideoCapture(source)` 打开设备，source 来自 `device_config.source`
   - `capture_frame`：调用 `cap.read()`，保存为 JPEG，释放 cap，返回路径
   - `is_available`：尝试打开设备，检查 `cap.isOpened()`
3. 在 `adapters/camera/directshow.py` 中实现 `DirectShowCameraAdapter`（Windows）：与 v4l2 相同逻辑，但使用 `cv2.VideoCapture(index, cv2.CAP_DSHOW)`
4. 在 `adapters/camera/avfoundation.py` 中实现 `AVFoundationCameraAdapter`（macOS）：使用 `cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)`
5. 在 `adapters/camera/__init__.py` 中实现 `get_camera_adapter(device_config, env_profile) -> CameraAdapter`，根据 `env_profile.camera_backend` 返回对应实现类实例
6. 编写 `tests/unit/test_camera_adapters.py`：mock `cv2.VideoCapture`，验证三个适配器的 `capture_frame` 均保存文件并返回正确路径

**验收标准**: mock 测试全部通过；在真实 Linux/Windows/macOS 环境下 `capture_frame` 生成有效 JPEG 文件

---

## T11 — 实现传感器适配器基类与三种传输实现

**对应**: plan-01.md S1-2 + §3.4 M-ADAPT-SEN

**执行步骤**:
1. 在 `adapters/sensor/base.py` 中定义抽象基类 `SensorAdapter`：
   - `__init__(self, device_config: DeviceConfig)`
   - 抽象方法 `async poll(self) -> BusMessage`
   - 抽象方法 `is_available(self) -> bool`
2. 在 `adapters/sensor/wifi_poll.py` 中实现 `WiFiPollAdapter`：
   - `poll`：使用 `httpx.AsyncClient` GET `device_config.poll_url`，解析 `{"value": float, "unit": str}` 响应，构造并返回 `BusMessage`
   - `is_available`：尝试 GET，返回 HTTP 200 则 True
3. 在 `adapters/sensor/bluetooth.py` 中实现 `BluetoothAdapter`：
   - 使用 `bleak.BleakClient` 连接设备，读取配置的 GATT characteristic UUID
   - `is_available`：检查 `env_profile.bluetooth_available`，若 False 直接返回 False
4. 在 `adapters/sensor/serial_adapter.py` 中实现 `SerialAdapter`：
   - 使用 `pyserial` 读取串口，解析行分隔 JSON `{"value": float, "unit": str}`
5. 在 `adapters/sensor/__init__.py` 中实现 `get_sensor_adapter(device_config, env_profile) -> SensorAdapter`，根据 `device_config.transport` 返回对应实现
6. 编写 `tests/unit/test_sensor_adapters.py`：mock `httpx.AsyncClient`，验证 `WiFiPollAdapter.poll()` 返回正确的 `BusMessage`

**验收标准**: WiFiPollAdapter mock 测试通过；`BusMessage.device_type == "sensor"`, `payload.type == "reading"`

---

## T12 — 实现设备数据总线核心（Ring Buffer + JSONL 持久化）

**对应**: plan-01.md S1-3 + §3.2 M-BUS

**执行步骤**:
1. 在 `core/bus/bus.py` 中实现 `DeviceDataBus` 类：
   - `__init__(self, ring_buffer_size: int = 1000)`
   - 内部维护 `_buffers: dict[str, asyncio.Queue]`，每个 device_id 一个 Queue
   - `async put(self, msg: BusMessage)`：将消息放入对应 device 的 Queue；若 Queue 已满，先 `get_nowait()` 丢弃最旧消息再放入（非阻塞）；同时追加写入 JSONL 持久化文件
   - `get_latest(self, device_id: str) -> BusMessage | None`：返回 Queue 中最新消息，不消费（peek）；若 Queue 为空返回 None
   - `get_history(self, device_id: str, from_iso: str, to_iso: str) -> list[BusMessage]`：从 JSONL 文件读取指定时间范围的消息
   - `get_stats(self, device_id: str, window_minutes: int) -> dict`：计算最近 N 分钟的 min/max/avg/trend
2. JSONL 持久化路径：`~/.clawtail/data/sensor_logs/{device_id}.jsonl`，每行一个 `BusMessage.to_dict()` JSON
3. `get_latest` 的 peek 实现：将 Queue 内容转为 list，取最后一个，再重新放回（注意线程安全，使用 asyncio 锁）
4. 在 `core/bus/__init__.py` 中暴露全局单例 `bus = DeviceDataBus()`
5. 编写 `tests/unit/test_bus.py`：测试 ring buffer 溢出行为（放入 1001 条消息，验证最旧的被丢弃）；测试 JSONL 持久化（put 后文件存在且内容正确）；测试 `get_history` 时间范围过滤

**验收标准**: ring buffer 溢出测试通过；JSONL 文件写入正确；`get_history` 返回正确时间范围内的消息

---

## T13 — 实现设备数据总线 Webhook 服务器（Push 路径）

**对应**: plan-01.md S1-4 + §3.2 M-BUS Webhook Server

**执行步骤**:
1. 在 `core/bus/webhook_server.py` 中使用 FastAPI 实现 Webhook 服务器：
   - 创建 `FastAPI` app
   - 实现 `POST /webhook/{device_id}` 端点：接收 JSON body `{"value": float, "unit": str, "meta": dict?}`，构造 `BusMessage`，调用 `bus.put(msg)`，返回 `{"status": "ok"}`
   - 同时触发内部事件 `device.push:{device_id}`（通过 event_bus，见 T22）
2. 服务器绑定 `127.0.0.1:{config.bus.webhook_port}`（仅 loopback，不暴露到 LAN）
3. 在 `core/bus/webhook_server.py` 中实现 `start_webhook_server()` 异步函数，使用 `uvicorn.Server` 在后台 asyncio task 中启动
4. 添加请求验证：device_id 必须在 `devices_config` 中已注册，否则返回 404
5. 编写 `tests/unit/test_webhook_server.py`：使用 `httpx.AsyncClient` + FastAPI `TestClient` 测试：合法 device_id 返回 200 且消息进入总线；未注册 device_id 返回 404

**验收标准**: Webhook 测试通过；`curl -X POST http://localhost:17171/webhook/lab_temp_sensor -d '{"value":25.3,"unit":"celsius"}'` 返回 `{"status":"ok"}`

---

## T14 — 实现设备数据总线 Poll Manager（Poll 路径）

**对应**: plan-01.md §3.2 M-BUS Poll Manager

**执行步骤**:
1. 在 `core/bus/poll_manager.py` 中实现 `PollManager` 类：
   - `__init__(self, devices_config: DevicesConfig, bus: DeviceDataBus, env_profile: EnvProfile)`
   - `start()`：遍历 `devices_config.devices`，对每个 `transport == "wifi_poll"` 的设备，创建一个 asyncio task 运行 `_poll_loop(device_config)`
   - `_poll_loop(device_config)`：无限循环，每次调用对应 `SensorAdapter.poll()`，将结果 `put` 到总线，然后 `asyncio.sleep(device_config.poll_interval_seconds)`
   - `stop()`：取消所有 asyncio tasks
2. 对 `transport == "wifi_push"` 的设备，Poll Manager 不创建 poll loop（由 Webhook Server 处理）
3. 对 `transport == "usb"` 的摄像头设备，Poll Manager 不处理（摄像头由 MCP Tool 按需采集）
4. 在 `core/bus/__init__.py` 中暴露 `poll_manager = PollManager(...)` 单例
5. 编写 `tests/unit/test_poll_manager.py`：mock `WiFiPollAdapter.poll()` 返回固定消息，验证 `PollManager.start()` 后消息进入总线

**验收标准**: Poll Manager 启动后，mock 传感器的消息每隔 `poll_interval_seconds` 出现在总线中

---

## T15 — 实现 `clawtail device` CLI 命令组

**对应**: plan-01.md S1-5 + §3.9 M-CLI（device 命令部分）

**执行步骤**:
1. 在 `cli/device.py` 中创建 `device_app = typer.Typer()`，注册到主 app
2. 实现 `clawtail device list` 命令：
   - 加载 `devices_config`
   - 对每个设备，调用对应 adapter 的 `is_available()`
   - 用 `rich.table.Table` 输出：device_id、type、transport、status（✅ available / ❌ unavailable）
3. 实现 `clawtail device test <device_id>` 命令：
   - 若 type == "camera"：调用 `capture_frame()`，输出保存路径和文件大小
   - 若 type == "sensor"：调用 `poll()`，输出读取到的 value 和 unit
   - 若 device_id 不存在：输出错误信息并退出 code 1
4. 实现 `clawtail start` 命令（骨架）：调用 `init_storage()`，启动 `PollManager`，启动 Webhook Server，输出 "ClawWithTail started"
5. 实现 `clawtail stop` 命令（骨架）：输出 "ClawWithTail stopped"（完整实现在 Sprint 3）

**验收标准**: `clawtail device list` 输出设备表格；`clawtail device test desk_camera` 在有摄像头时输出帧文件路径

---

## T16 — 编写 Sprint 1 集成冒烟测试

**对应**: plan-01.md §7 Testing Strategy（Sprint 1 范围）

**执行步骤**:
1. 在 `tests/integration/test_bus_pipeline.py` 中编写端到端测试：
   - 启动 Webhook Server（使用 `TestClient`）
   - POST 一条传感器数据到 `/webhook/plant_soil_sensor`
   - 验证 `bus.get_latest("plant_soil_sensor")` 返回正确的 `BusMessage`
   - 验证 `~/.clawtail/data/sensor_logs/plant_soil_sensor.jsonl` 文件存在且包含该条记录
2. 在 `tests/integration/test_camera_capture.py` 中编写测试（需要 mock cv2）：
   - mock `cv2.VideoCapture` 返回固定图像数据
   - 调用 `V4L2CameraAdapter.capture_frame(tmp_path)`
   - 验证文件存在，大小 > 0
3. 在 `tests/integration/test_poll_manager.py` 中编写测试：
   - mock `WiFiPollAdapter.poll()` 返回固定消息
   - 启动 `PollManager`，等待 2 个 poll 周期
   - 验证总线中有 2 条消息，JSONL 文件有 2 行

**验收标准**: `pytest tests/integration/` 全部通过（使用 mock，不依赖真实硬件）
