# Tasks-03 — Sprint 2: MCP Tool Packages

> **Source**: plan-01.md §6 Sprint 2 + §4 MCP Tool Package Implementation Details
> **Sprint**: Sprint 2 (Week 5–7)
> **Goal**: 5 个 MCP Tool Package 全部实现并可通过 MCP 协议调用，`vision.start_watch` 后台监控可运行

---

## T17 — 实现 MCP Tool Package 公共基础设施

**对应**: plan-01.md §4 开头的公共 startup pattern

**执行步骤**:
1. 在 `tools/shared/mcp_base.py` 中实现公共 MCP Server 启动模板：
   ```python
   from mcp.server import Server
   from mcp.server.stdio import stdio_server

   def create_mcp_server(name: str) -> Server:
       return Server(name)

   async def run_server(app: Server):
       async with stdio_server() as (read, write):
           await app.run(read, write, app.create_initialization_options())
   ```
2. 在 `tools/shared/errors.py` 中定义 `ToolError(Exception)` 基类，包含 `message` 和 `tool_name` 字段
3. 在 `tools/shared/config.py` 中实现 `get_tool_config()` 函数，从全局 `app_config` 中提取 Tool 相关配置（LLM model、Feishu webhook、Tavily key 等）
4. 在 `core/agent/tool_registry.py` 中实现 `ToolRegistry` 类：
   - `register(tool_name: str, mcp_server_process)`：注册 MCP server 进程
   - `get_all_tools() -> list[dict]`：返回所有已注册工具的 JSON Schema 描述（通过 MCP `list_tools` 调用获取）
   - `dispatch(tool_name: str, args: dict) -> str`：路由到正确的 MCP server，发送 JSON-RPC 调用，返回结果字符串
5. 编写 `tests/unit/test_tool_registry.py`：mock MCP server，验证 `dispatch` 路由正确

**验收标准**: `ToolRegistry.dispatch("vision.capture_frame", {...})` 能路由到 vision MCP server 并返回结果

---

## T18 — 实现 `vision` MCP Tool Package（capture/detect/analyze/compare/count）

**对应**: plan-01.md S2-1 + §4.1 vision Tool Package（start_watch 除外）

**执行步骤**:
1. 在 `tools/vision/server.py` 中创建 MCP Server `app = Server("vision-tools")`
2. 实现 `vision.capture_frame(source_id: str, save_path: str | None) -> dict`：
   - 从 `camera_registry` 获取对应适配器（registry 在 server 启动时根据 `env_profile` 初始化）
   - 调用 `adapter.capture_frame(path)`，返回 `{"frame_path": str, "timestamp": str}`
3. 实现 `vision.detect_objects(frame_path: str, confidence: float = 0.5) -> list[dict]`：
   - 加载 YOLOv8 模型（`yolo_variant` 来自 `env_profile`，首次调用时通过 `ultralytics` 自动下载到 `~/.clawtail/models/`）
   - 运行推理，返回 `[{"label": str, "confidence": float, "bbox": [x1,y1,x2,y2]}]`
4. 实现 `vision.analyze_image(frame_path: str, prompt: str) -> dict`：
   - 读取图像文件，base64 编码
   - 调用 LiteLLM `vision_model`，传入 image_url + prompt
   - 返回 `{"analysis_text": str}`；base64 数据不出现在返回值中
5. 实现 `vision.compare_frames(frame_path_a: str, frame_path_b: str, prompt: str | None) -> dict`：
   - 将两张图同时传给视觉模型，prompt 默认为 "Describe the differences between these two images"
   - 返回 `{"diff_description": str}`
6. 实现 `vision.count_objects(event_log_path: str, label: str, window_minutes: int) -> dict`：
   - 读取 JSONL 事件日志文件，过滤最近 `window_minutes` 分钟内 label 匹配的事件
   - 返回 `{"count": int, "window_minutes": int}`
7. 在 `tools/vision/camera_registry.py` 中实现 `CameraRegistry`，在 server 启动时根据 `devices_config` 和 `env_profile` 初始化所有摄像头适配器

**验收标准**: 通过 MCP 协议调用 `vision.capture_frame` 返回有效 frame_path；`vision.detect_objects` 对测试图片返回检测结果列表

---

## T19 — 实现 `vision.start_watch` 后台监控工具

**对应**: plan-01.md S2-6 + §4.1 vision.start_watch

**执行步骤**:
1. 在 `tools/vision/watcher.py` 中实现 `_watch_loop` 协程，完全按照 plan-01.md §4.1 的代码逻辑：
   - 每 `interval_seconds` 秒捕获一帧
   - 调用 `detect_objects` 检测
   - 若检测到 `labels` 中的任意标签，追加写入 `event_log_path` JSONL 文件，然后 `asyncio.sleep(cooldown_seconds)`
   - 否则 `asyncio.sleep(interval_seconds)`
2. 在 `tools/vision/server.py` 中实现 `vision.start_watch(source_id, labels, interval_seconds=30, cooldown_seconds=300, event_log_path=None) -> dict`：
   - 生成 `watcher_id = str(uuid4())`
   - 使用 `asyncio.create_task(_watch_loop(...))` 启动后台协程
   - 将 `watcher_id → task` 存入模块级 `_watchers: dict` 字典
   - 返回 `{"watcher_id": str, "status": "started"}`
3. 实现 `vision.stop_watch(watcher_id: str) -> dict`：
   - 从 `_watchers` 取出 task，调用 `task.cancel()`
   - 返回 `{"watcher_id": str, "status": "stopped"}`
4. 事件日志格式（每行一条）：`{"timestamp": "ISO8601", "labels": ["cup"], "confidences": [0.87]}`
5. 编写 `tests/unit/test_watcher.py`：
   - mock `capture_frame` 和 `detect_objects`
   - 启动 watcher，注入 3 次检测到 "cup" 的结果
   - 验证 event_log_path 文件有 3 行（cooldown 期间不重复记录）

**验收标准**: watcher 启动后后台运行；检测到目标时写入事件日志；cooldown 期间不重复记录；`stop_watch` 正确停止协程

---

## T20 — 实现 `sensor` MCP Tool Package

**对应**: plan-01.md S2-2 + §4.2 sensor Tool Package

**执行步骤**:
1. 在 `tools/sensor/server.py` 中创建 MCP Server `app = Server("sensor-tools")`
2. 实现 `sensor.list_devices() -> list[dict]`：
   - 读取 `devices_config`，过滤 `type == "sensor"` 的设备
   - 对每个设备调用 `bus.get_latest(device_id)` 判断是否有数据
   - 返回 `[{"device_id": str, "type": str, "status": "active|no_data"}]`
3. 实现 `sensor.read_latest(device_id: str) -> dict`：
   - 调用 `bus.get_latest(device_id)`
   - 若为 None，raise `ToolError(f"No data available for device {device_id}")`
   - 返回 `{"value": float, "unit": str, "timestamp": str}`
4. 实现 `sensor.read_history(device_id: str, from_iso: str, to_iso: str) -> list[dict]`：
   - 调用 `bus.get_history(device_id, from_iso, to_iso)`
   - 返回 `[{"value": float, "unit": str, "timestamp": str}]`
5. 实现 `sensor.get_stats(device_id: str, from_iso: str, to_iso: str) -> dict`：
   - 调用 `bus.get_history` 获取原始数据
   - 计算 min/max/avg
   - 计算 trend：取前 1/3 和后 1/3 的均值，差值 > 5% 则为 rising/falling，否则 stable
   - 返回 `{"min": float, "max": float, "avg": float, "trend": "rising|falling|stable"}`
6. 编写 `tests/unit/test_sensor_tools.py`：mock `bus.get_latest` 返回 None → 验证 ToolError；mock 返回有效数据 → 验证返回格式正确

**验收标准**: `sensor.read_latest` 在无数据时抛出 ToolError；`sensor.get_stats` 对 fixture 数据返回正确的 trend

---

## T21 — 实现 `storage` MCP Tool Package

**对应**: plan-01.md S2-3 + §4.3 storage Tool Package

**执行步骤**:
1. 在 `tools/storage/server.py` 中创建 MCP Server `app = Server("storage-tools")`
2. 实现 `storage.save_summary(content: str, category: str, tags: list[str] | None) -> dict`：
   - 生成 UUID 作为 summary_id
   - 构造 meta dict（id, category, tags, created_at）
   - 写入 `~/.clawtail/summaries/{summary_id}.json`
   - 返回 `{"summary_id": str, "path": str}`
3. 实现 `storage.read_summary(summary_id: str) -> dict`：
   - 读取对应 JSON 文件，返回 `{"content": str, "metadata": dict}`
   - 若文件不存在，raise `ToolError`
4. 实现 `storage.list_summaries(category: str | None, tags: list[str] | None, from_iso: str | None, to_iso: str | None, last_n: int | None) -> list[dict]`：
   - 扫描 `~/.clawtail/summaries/` 目录，加载所有 JSON 文件的 meta
   - 按 category/tags/时间范围过滤
   - 若指定 `last_n`，按 created_at 降序取前 N 条
   - 返回 `[{"summary_id": str, "category": str, "tags": list, "created_at": str, "snippet": str}]`（snippet 为 content 前 200 字符）
5. 实现 `storage.save_report(content: str, title: str, task_id: str) -> dict`：
   - 文件名格式：`{date}_{task_id}_{slugify(title)}.md`
   - 写入 `~/.clawtail/data/reports/`
   - 返回 `{"report_path": str}`
6. 实现 `storage.read_report(report_path: str) -> dict`：
   - 安全检查：report_path 必须在 `~/.clawtail/data/reports/` 下（防路径穿越）
   - 读取文件内容，返回 `{"content": str}`
7. 编写 `tests/unit/test_storage_tools.py`：使用 `tmp_path` fixture，验证 save/read/list 的完整往返

**验收标准**: save → list → read 往返测试通过；路径穿越攻击（`../../../etc/passwd`）被拒绝

---

## T22 — 实现 `notify` MCP Tool Package 与内部事件总线

**对应**: plan-01.md S2-4 + §4.4 notify Tool Package + §3.8 event_bus

**执行步骤**:
1. 在 `core/scheduler/event_bus.py` 中实现轻量级内部事件总线：
   - `subscribe(event: str, callback: Callable)`：注册事件监听器
   - `publish(event: str, data: dict | None = None)`：触发所有该事件的监听器（asyncio-safe）
   - 支持通配符事件名（如 `device.push:*` 匹配所有 device push 事件）
2. 在 `tools/notify/server.py` 中创建 MCP Server `app = Server("notify-tools")`
3. 实现 `notify.feishu_send(message: str, webhook_url: str | None) -> dict`：
   - `url = webhook_url or app_config.notify.feishu_default_webhook`
   - 使用 `httpx.AsyncClient` POST `{"msg_type": "text", "content": {"text": message}}`
   - 返回 `{"success": bool, "status_code": int}`
4. 实现 `notify.feishu_send_report(title: str, summary: str, report_path: str) -> dict`：
   - 构造格式化消息：`📋 **{title}**\n\n{summary}\n\n📁 Report saved: \`{report_path}\``
   - 调用 `feishu_send` 发送
   - 返回 `{"success": bool}`
5. 编写 `tests/unit/test_notify_tools.py`：mock `httpx.AsyncClient.post` 返回 200，验证 `feishu_send` 返回 `{"success": True}`；mock 返回 500，验证返回 `{"success": False}`
6. 编写 `tests/unit/test_event_bus.py`：验证 subscribe + publish 触发回调；验证通配符匹配

**验收标准**: `notify.feishu_send` mock 测试通过；event_bus publish 正确触发所有订阅者

---

## T23 — 实现 `knowledge` MCP Tool Package

**对应**: plan-01.md S2-5 + §4.5 knowledge Tool Package

**执行步骤**:
1. 在 `tools/knowledge/server.py` 中创建 MCP Server `app = Server("knowledge-tools")`
2. 实现 `knowledge.search_web(query: str, max_results: int = 5) -> list[dict]`：
   - 使用 `tavily-python` 客户端，API key 来自 `app_config.knowledge.tavily_api_key`
   - 返回 `[{"title": str, "snippet": str, "url": str}]`
   - 若 `search_provider != "tavily"`，raise `ToolError("Only tavily supported in MVP")`
3. 实现 `knowledge.identify_plant(frame_path: str) -> dict`：
   - 构造 prompt（按 plan-01.md §4.5 的 prompt 模板）
   - 调用 LiteLLM vision model（复用 `vision.analyze_image` 的图像编码逻辑，但在 knowledge 包内独立实现，不跨包调用）
   - 解析返回的 JSON，返回 `{"species": str, "common_name": str, "confidence": str, "care_summary": str}`
   - 若 LLM 返回非 JSON，返回 `{"species": "unknown", "common_name": "unknown", "confidence": "low", "care_summary": ""}`
4. 实现 `knowledge.fetch_care_guide(species_name: str) -> dict`：
   - 先检查 `~/.clawtail/cache/care_guides/{slugify(species_name)}.json` 是否存在
   - 若存在，直接返回缓存内容
   - 若不存在，调用 `search_web` 搜索，再调用 LLM 提取结构化 care guide，写入缓存，返回结果
   - 返回 `{"watering": str, "light": str, "temperature": str, "humidity": str, "notes": str}`
5. 实现 `knowledge.search_local_kb(query: str, category: str | None) -> list[dict]`：
   - 加载 `~/.clawtail/summaries/` 下所有 JSON 文件（按 category 过滤）
   - 对每个 summary 计算关键词匹配分数（query 中每个词在 content 中出现次数之和）
   - 按分数降序排列，返回前 10 条，分数为 0 的过滤掉
   - 返回 `[{"summary_id": str, "relevance_score": float, "snippet": str}]`（snippet 为 content 前 300 字符）
6. 编写 `tests/unit/test_knowledge_tools.py`：mock Tavily client；mock LLM 返回固定 JSON；验证 `fetch_care_guide` 第二次调用走缓存（不调用 search_web）

**验收标准**: `fetch_care_guide` 缓存命中测试通过（第二次调用不触发网络请求）；`search_local_kb` 关键词匹配返回正确排序

---

## T24 — 编写 Sprint 2 MCP Tool 集成测试

**对应**: plan-01.md §7.1 Unit Tests（Tool 部分）

**执行步骤**:
1. 在 `tests/integration/test_vision_tools.py` 中编写测试：
   - mock `cv2.VideoCapture` 返回固定图像
   - mock LiteLLM 返回固定分析文本
   - 调用 `vision.capture_frame` → `vision.analyze_image` 完整链路
   - 验证 `analyze_image` 的返回值中不包含 base64 字符串
2. 在 `tests/integration/test_storage_tools.py` 中编写测试：
   - 调用 `storage.save_summary` 保存 3 条不同 category 的 summary
   - 调用 `storage.list_summaries(category="plant_monitor", last_n=2)` 验证只返回 2 条
   - 调用 `storage.save_report` 保存报告，再调用 `storage.read_report` 验证内容一致
3. 在 `tests/integration/test_watcher_pipeline.py` 中编写测试：
   - mock camera 和 YOLO 模型
   - 启动 `vision.start_watch`，注入 2 次检测到 "cup" 的帧，1 次未检测到
   - 等待足够时间后调用 `vision.count_objects`
   - 验证 count == 2（cooldown 内的重复不计）
   - 调用 `vision.stop_watch` 验证后台任务停止

**验收标准**: 所有集成测试通过；`analyze_image` 返回值不含 base64 数据
