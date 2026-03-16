# Tasks-05 — Sprint 4: Integration, Demo Wiring & Release

> **Source**: plan-01.md §6 Sprint 4 + §5 Demo Scenario Wiring + §7 Testing Strategy
> **Sprint**: Sprint 4 (Week 11–12)
> **Goal**: 三个 Demo 端到端可运行，CLI 完整可用，MVP 可对外发布

---

## T31 — 端到端接线：植物浇水提醒 Demo（Self-Planning 流程）

**对应**: plan-01.md S4-1 + §5.1 Plant Watering Reminder

**执行步骤**:
1. 在 `tasks/examples/plant_monitor.json` 中确认示例 Task JSON 符合 Self-Planning 输出格式（由 T07 创建），内容对应 plan-01.md §5.1 的 "Generated Task design"：
   - trigger: cron, `"0 */2 * * *"`（每 2 小时）
   - goal: "Assess the current health and hydration status of the plant. Check both visual appearance and soil moisture data against the care guide for this species. If watering is needed, send a Feishu alert. Always save a summary."
   - constraints: `["Do not call vision.analyze_image more than 3 times per run", "Always save a summary before sending a notification"]`
   - context: include_summaries(category="plant_monitor", last_n=3), include_sensor_stats(device_ids=["plant_soil_sensor"], window_minutes=120)
2. 编写 `tests/integration/test_demo_plant.py`（按 plan-01.md §7.2 规格）：
   - mock camera adapter 返回 fixture JPEG（一张绿色植物图）
   - mock sensor adapter 返回 `{"value": 22.5, "unit": "percent"}`（低于 30% 阈值）
   - mock LiteLLM：第一次调用返回 `vision.capture_frame` tool call；第二次返回 `vision.analyze_image` tool call；第三次返回 `sensor.read_latest` tool call；第四次返回 final_answer（含浇水建议）
   - mock `httpx.AsyncClient.post`（Feishu webhook）
   - 运行 `TaskRunner.run(plant_monitor_task)`
   - 断言：`storage.save_summary` 被调用；Feishu webhook POST 被调用（因为 soil < 30%）；`AgentRunResult.status == "success"`
3. 验证 Self-Planning 流程：运行 `clawtail task generate "Monitor and care for the plant on my desk"`（mock LLM 返回合法 TaskConfig JSON），验证生成的 JSON 文件保存到 `~/.clawtail/tasks/`

**验收标准**: `test_demo_plant.py` 全部断言通过；Self-Planning 生成的 Task JSON 通过 schema 验证

---

## T32 — 端到端接线：化学实验监控 Demo

**对应**: plan-01.md S4-2 + §5.2 Chemistry Experiment Monitor

**执行步骤**:
1. 确认 `tasks/examples/chemistry_monitor.json` 内容对应 plan-01.md §5.2：
   - trigger: cron, `"*/15 * * * *"`（每 15 分钟）
   - goal: "Capture the current state of the experiment. Compare with the previous frame. Describe any observable changes (color, precipitate, gas bubbles, volume change). Save a timestamped summary. If significant change is detected, send an immediate Feishu alert."
   - context: include_summaries(category="chem_experiment", last_n=1)
   - output: save_report=true, notify.trigger="on_anomaly"
2. 编写 `tests/integration/test_demo_chemistry.py`：
   - mock camera 返回两张不同的 fixture JPEG（模拟实验前后）
   - mock LiteLLM：`vision.compare_frames` 返回 "Yellow precipitate forming"；`vision.analyze_image` 返回详细描述；final_answer 包含 "significant change detected"
   - 运行 TaskRunner 执行 chemistry_monitor task
   - 断言：`storage.save_summary` 被调用；Feishu webhook 被调用（因为 on_anomaly 且 LLM 判断有显著变化）
3. 测试实验结束报告生成：
   - 预先在 `~/.clawtail/summaries/` 中放入 5 条 category="chem_experiment" 的 fixture summaries
   - 创建一个 `chemistry_report.json` task（trigger: manual，goal: "Generate a complete experiment log from all summaries"）
   - 运行该 task，验证 `storage.save_report` 被调用，生成的 Markdown 文件存在且包含 "Timeline" 章节

**验收标准**: `test_demo_chemistry.py` 全部断言通过；实验报告 Markdown 文件生成正确

---

## T33 — 端到端接线：饮水提醒 Demo（双层架构）

**对应**: plan-01.md S4-3 + §5.3 Drinking Water Reminder

**执行步骤**:
1. 确认 `tasks/examples/drinking_watcher.json` 内容对应 plan-01.md §5.3 的 Watcher Task：
   - trigger: on_event, event="system.start"
   - goal: "Start a background watcher to monitor drinking activity"
   - constraints: `["Call vision.start_watch with source_id='desk_camera', labels=['cup','bottle','drinking glass'], interval_seconds=30, cooldown_seconds=300"]`
2. 确认 `tasks/examples/drinking_summarizer.json` 内容对应 Summarizer Task：
   - trigger: cron, `"0 */90 * * * *"`（每 90 分钟）
   - goal: "Review the drinking activity log for the past 90 minutes. Compare against a healthy hydration baseline (at least 1 drink per 90 minutes). If insufficient, send a Feishu hydration reminder. Save a daily summary."
   - context: include_summaries(category="hydration", last_n=3)
3. 编写 `tests/integration/test_demo_drinking.py`（按 plan-01.md §7.2 规格）：
   - **场景 A（充足饮水）**：
     - 预先在 event_log 中写入 3 条 fixture 事件（过去 90 分钟内）
     - mock LiteLLM：`vision.count_objects` 返回 `{"count": 3}`；final_answer 为 "Hydration adequate"
     - 运行 summarizer task，断言：Feishu webhook **未**被调用；`storage.save_summary` 被调用
   - **场景 B（饮水不足）**：
     - event_log 为空（0 条事件）
     - mock LiteLLM：`vision.count_objects` 返回 `{"count": 0}`；final_answer 包含 "insufficient"
     - 运行 summarizer task，断言：Feishu webhook **被**调用，消息包含 "💧"
4. 测试 watcher 启动流程：
   - 触发 `system.start` 事件
   - 验证 `vision.start_watch` 被调用（通过 mock ToolDispatcher 记录调用）

**验收标准**: 场景 A 和 B 的断言全部通过；watcher 在 system.start 时自动启动

---

## T34 — 系统启动全链路冒烟测试

**对应**: plan-01.md §7 Testing Strategy（全系统）

**执行步骤**:
1. 在 `tests/integration/test_system_startup.py` 中编写全链路启动测试：
   - mock 所有外部依赖（cv2、LiteLLM、httpx、Tavily）
   - 调用完整启动序列：`init_storage()` → `get_env_profile()` → `PollManager.start()` → `start_webhook_server()` → `task_scheduler.load_tasks()` → `task_scheduler.start()`
   - 验证：所有 MCP Tool Server 进程已注册到 ToolRegistry；`task_scheduler` 中有 3 个已注册的 task（来自 examples/）；`system.start` 事件已触发
2. 在 `tests/integration/test_full_react_loop.py` 中编写完整 ReAct 循环测试：
   - 使用真实的 `ReactLoop`、`ContextBudget`、`ContextBuilder`（不 mock）
   - mock LiteLLM 和 MCP Tool 调用
   - 运行 plant_monitor task 的完整 ReAct 循环（4 步）
   - 验证：`AgentRunResult.tool_calls` 长度为 3；`final_summary` 非空；context budget 未超出 8000 tokens
3. 验证 CLI 端到端：
   - 使用 Typer `CliRunner` 运行 `clawtail task validate tasks/examples/plant_monitor.json`，验证输出 "✅ Valid"
   - 运行 `clawtail task validate` 对一个故意损坏的 JSON，验证输出包含错误信息

**验收标准**: 全链路启动测试通过；完整 ReAct 循环测试通过；CLI 验证命令正确工作

---

## T35 — 硬件在环手动测试清单与测试报告模板

**对应**: plan-01.md §7.3 Hardware-in-the-Loop Tests

**执行步骤**:
1. 在 `docs/testing/hardware_test_checklist.md` 中创建硬件测试清单，包含以下测试项（每项含预期结果和实际结果填写栏）：
   - **摄像头测试**（Linux / Windows / macOS 各一行）：`clawtail device test desk_camera` → 输出 JPEG 路径，文件大小 > 10KB
   - **传感器 WiFi Poll 测试**：启动 ESP32 mock server，`clawtail device test plant_soil_sensor` → 输出 value 和 unit
   - **Feishu Webhook 测试**：手动调用 `notify.feishu_send`，验证飞书群收到消息
   - **YOLOv8 首次下载测试**：删除 `~/.clawtail/models/`，运行 `vision.detect_objects`，验证自动下载并缓存
   - **植物浇水 Demo 真实运行**：接入真实摄像头和土壤传感器，运行 `clawtail task run plant_monitor`，验证飞书收到提醒
   - **饮水提醒 Demo 真实运行**：接入摄像头，拿起水杯喝水，等待 90 分钟，验证飞书收到汇总
2. 在 `docs/testing/` 目录下创建 `test_report_template.md`，包含：测试日期、测试环境（OS/GPU/摄像头型号）、各测试项结果（Pass/Fail/Skip）、发现的 Bug 列表

**验收标准**: 清单文件创建完成；在至少一个真实 OS 环境下完成所有 Pass 项

---

## T36 — 项目 README 与快速开始文档

**对应**: plan-01.md S4-6

**执行步骤**:
1. 在项目根目录创建 `README.md`，包含以下章节：
   - **What is ClawWithTail**：一段话描述（参考 spec.md §1.1 Vision）
   - **Architecture**：复制 spec.md §2.1 的 ASCII 架构图
   - **Quick Start**（5 步）：
     1. `git clone` + `pip install -e .`
     2. 复制 `.env.example` 为 `.env`，填入 API keys
     3. 编辑 `config/devices.yaml` 注册设备
     4. `clawtail env check`（验证环境）
     5. `clawtail start`
   - **Demo Scenarios**：三个 Demo 的简短描述 + 运行命令
   - **Adding a New Task**：说明如何编写 Task JSON 或使用 `clawtail task generate`
   - **License**：GPL-3.0
2. 在 `docs/` 下创建 `contributing.md`，说明：
   - 如何添加新的 MCP Tool Package（参考 `tools/vision/` 结构）
   - 如何添加新的设备适配器（继承 `CameraAdapter` 或 `SensorAdapter`）
   - 如何添加新的通知渠道（在 `tools/notify/` 中添加新 tool）
   - 代码风格：Black + isort，类型注解必须，docstring 必须

**验收标准**: README 中的 Quick Start 5 步在干净环境下可完整执行；`contributing.md` 覆盖三种扩展场景
