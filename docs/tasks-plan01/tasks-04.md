# Tasks-04 — Sprint 3: Agent & Orchestration

> **Source**: plan-01.md §6 Sprint 3 + §3.5 M-LLM + §3.6 M-AGENT + §3.7 M-TASK + §3.8 M-SCHED
> **Sprint**: Sprint 3 (Week 8–10)
> **Goal**: LLM 引擎、ReAct 编排循环、Task Runner、调度器全部就绪，Agent 可端到端执行一个 Task

---

## T25 — 实现 LiteLLM 封装层与上下文预算管理器

**对应**: plan-01.md S3-1 + §3.5 M-LLM

**执行步骤**:
1. 在 `core/agent/llm_engine.py` 中实现 `LLMEngine` 类：
   - `__init__(self, config: LLMConfig)`：初始化 LiteLLM，设置 API keys（从环境变量读取）
   - `async complete(self, messages: list[dict], tools: list[dict] | None, model: str | None) -> dict`：
     - 调用 `litellm.acompletion(model=model or config.default_model, messages=messages, tools=tools)`
     - 实现指数退避重试（最多 3 次，间隔 2^n 秒），仅对 rate limit 错误（429）重试
     - 返回原始 response 对象
   - `async complete_vision(self, frame_path: str, prompt: str) -> str`：
     - 读取图像文件，base64 编码
     - 构造 vision message，调用 `config.vision_model`
     - 返回文本响应
2. 在 `core/agent/context_budget.py` 中实现 `ContextBudget` 类：
   - 常量：`SYSTEM_PROMPT_MAX=1000`, `SUMMARIES_MAX=2000`, `SENSOR_STATS_MAX=500`, `TOOL_HISTORY_MAX=3000`, `TOTAL_MAX=8000`
   - `estimate_tokens(text: str) -> int`：简单估算（字符数 / 4，不依赖 tiktoken）
   - `truncate_to_budget(text: str, max_tokens: int) -> str`：按 token 预算截断文本，在末尾加 `"...[truncated]"`
   - `build_messages(self, task: TaskConfig, context: AgentContext, tool_history: list[dict]) -> list[dict]`：
     - 组装 system prompt（含 task goal + constraints），截断到 `SYSTEM_PROMPT_MAX`
     - 注入 summaries，截断到 `SUMMARIES_MAX`
     - 注入 sensor_stats，截断到 `SENSOR_STATS_MAX`
     - 注入 tool_history，截断到 `TOOL_HISTORY_MAX`
     - 返回完整 messages list
3. 编写 `tests/unit/test_llm_engine.py`：mock `litellm.acompletion`，验证 429 错误触发重试；验证第 4 次失败时抛出异常

**验收标准**: 429 重试逻辑测试通过；`build_messages` 在各 section 超出预算时正确截断

---

## T26 — 实现 ReAct 编排循环与 Tool Dispatcher

**对应**: plan-01.md S3-2 + §3.6 M-AGENT

**执行步骤**:
1. 在 `core/agent/react_loop.py` 中实现 `ReactLoop` 类：
   - `__init__(self, llm_engine: LLMEngine, tool_registry: ToolRegistry, budget: ContextBudget)`
   - `async run(self, task: TaskConfig, context: AgentContext) -> AgentRunResult`：
     - 初始化 `tool_history = []`, `step_count = 0`
     - 循环（最多 `task.max_steps` 步，默认 20）：
       1. **REASON**：调用 `budget.build_messages(task, context, tool_history)` 组装消息，调用 `llm_engine.complete(messages, tools=tool_registry.get_all_tools())`
       2. 解析响应：若有 `tool_calls`，进入 ACT；若无（final answer），退出循环
       3. **ACT**：对每个 tool_call，调用 `tool_dispatcher.dispatch(tool_name, args)`
       4. **OBSERVE**：将 tool_call + result 追加到 `tool_history`
     - 超出步数限制时，status = "step_limit_reached"
     - 超出 10 分钟硬超时时，status = "failed"，error = "timeout"
     - 返回 `AgentRunResult`
2. 在 `core/agent/tool_dispatcher.py` 中实现 `ToolDispatcher` 类：
   - `dispatch(self, tool_name: str, args: dict) -> str`：
     - 从 `ToolRegistry` 找到对应 MCP server
     - 构造 MCP JSON-RPC 请求：`{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool_name, "arguments": args}}`
     - 通过 stdio 发送到 MCP server 进程，读取响应
     - 返回 JSON 序列化的结果字符串
   - 若 tool_name 不存在，返回 `{"error": "Tool not found: {tool_name}"}`
3. 编写 `tests/unit/test_react_loop.py`：
   - mock LLM 第一次返回 tool_call，第二次返回 final_answer
   - 验证 `AgentRunResult.status == "success"`, `len(tool_calls) == 1`
   - mock LLM 始终返回 tool_call（不终止）
   - 验证 step_count 达到 max_steps 后 status == "step_limit_reached"

**验收标准**: ReAct 循环在 2 步内完成的测试通过；步数限制测试通过；超时测试通过

---

## T27 — 实现 Task Runner（Context Builder + 执行状态管理）

**对应**: plan-01.md S3-3 + S3-4 + §3.7 M-TASK

**执行步骤**:
1. 在 `core/task_runner/context_builder.py` 中实现 `ContextBuilder` 类：
   - `build(self, task: TaskConfig) -> AgentContext`：
     - 若 `task.context.include_summaries` 非空：调用 `storage.list_summaries(category, last_n)` 获取摘要列表，提取 content 字段
     - 若 `task.context.include_sensor_stats` 非空：对每个 device_id 调用 `bus.get_stats(device_id, window_minutes)` 获取统计数据
     - 返回 `AgentContext(summaries=list[str], sensor_stats=dict[str, dict])`
2. 在 `core/task_runner/state.py` 中实现 `TaskRunState` 类：
   - 维护当前运行的 run_id、started_at、step_count
   - `save_result(result: AgentRunResult)`：将结果写入 `~/.clawtail/logs/runs/{task_id}/{run_id}.json`
3. 在 `core/task_runner/runner.py` 中实现 `TaskRunner` 类：
   - `async run(self, task: TaskConfig) -> AgentRunResult`：
     1. 生成 run_id（UUID）
     2. 调用 `ContextBuilder.build(task)` 构建上下文
     3. 调用 `ReactLoop.run(task, context)` 执行 Agent
     4. 处理 output policy：若 `task.output.save_report == True` 且 result 包含报告内容，调用 `storage.save_report`
     5. 处理通知 policy：根据 `task.output.notify.trigger`（always/on_anomaly/on_complete）决定是否调用 `notify.feishu_send_report`
     6. 调用 `state.save_result(result)` 持久化
     7. 触发事件 `task.complete:{task.task_id}`
     8. 返回 `AgentRunResult`
4. 编写 `tests/unit/test_task_runner.py`：mock ReactLoop 返回固定 AgentRunResult，验证 output policy 正确执行（save_report 被调用；notify 在 on_anomaly 时仅在 result 包含异常标记时调用）

**验收标准**: Task Runner 完整执行流程测试通过；run 结果正确持久化到 `~/.clawtail/logs/runs/`

---

## T28 — 实现调度器（Cron + 事件触发）

**对应**: plan-01.md S3-5 + §3.8 M-SCHED

**执行步骤**:
1. 在 `core/scheduler/scheduler.py` 中实现 `TaskScheduler` 类：
   - `__init__(self, task_runner: TaskRunner, event_bus: EventBus)`
   - 内部使用 `APScheduler.AsyncIOScheduler`
   - `load_tasks(tasks_dir: str)`：扫描 `~/.clawtail/tasks/` 目录，加载所有 `.json` 文件，调用 `register_task` 注册
   - `register_task(task: TaskConfig)`：
     - 若 `trigger.type == "cron"`：调用 `scheduler.add_job(task_runner.run, CronTrigger.from_crontab(trigger.cron), args=[task], id=task.task_id)`
     - 若 `trigger.type == "on_event"`：调用 `event_bus.subscribe(trigger.event, lambda: asyncio.create_task(task_runner.run(task)))`
     - 若 `trigger.type == "manual"`：不注册自动触发，仅记录到 registry
   - `start()`：调用 `scheduler.start()`，触发 `system.start` 事件
   - `stop()`：调用 `scheduler.shutdown()`
   - `run_now(task_id: str)`：立即触发指定 task（用于 CLI 手动触发）
2. 在 `core/scheduler/__init__.py` 中暴露全局单例 `task_scheduler`
3. 编写 `tests/unit/test_scheduler.py`：
   - mock TaskRunner.run
   - 注册一个 cron task（每秒触发），等待 2 秒，验证 run 被调用 ≥ 2 次
   - 注册一个 on_event task，publish 对应事件，验证 run 被调用 1 次

**验收标准**: cron 触发测试通过；event 触发测试通过；`run_now` 立即执行测试通过

---

## T29 — 实现 Self-Planning Mode（LLM 自主生成 Task）

**对应**: plan-01.md S3-6 + §3.6 Self-Planning Mode + spec.md §3.3

**执行步骤**:
1. 在 `core/agent/self_planner.py` 中实现 `SelfPlanner` 类：
   - `async plan(self, goal: str) -> TaskConfig`：
     1. 构造 planning system prompt：说明 Agent 的角色是"根据目标生成一个 TaskConfig JSON"，提供 TaskConfig JSON Schema 作为输出格式约束
     2. 给 planning agent 提供的工具集：仅限 `knowledge.*` 和 `storage.list_summaries`（不允许调用 vision/sensor/notify）
     3. 运行 ReactLoop（最多 10 步），goal 为 "Generate a TaskConfig JSON for: {goal}"
     4. 从 final_answer 中提取 JSON（使用正则或 `json.loads` 尝试解析）
     5. 调用 `validate_task(task_dict)` 验证生成的 JSON
     6. 若验证失败，重试一次（最多 2 次总尝试）
     7. 将生成的 TaskConfig 保存到 `~/.clawtail/tasks/{task_id}.json`
     8. 返回 `TaskConfig`
2. 在 `core/agent/self_planner.py` 中实现 `_extract_json_from_text(text: str) -> dict | None`：
   - 尝试直接 `json.loads(text)`
   - 若失败，用正则提取 ` ```json ... ``` ` 代码块内容再解析
   - 若仍失败，返回 None
3. 编写 `tests/unit/test_self_planner.py`：
   - mock ReactLoop 返回包含合法 TaskConfig JSON 的 final_answer
   - 验证 `plan()` 返回正确的 `TaskConfig`，文件被保存到 tasks 目录
   - mock ReactLoop 返回非法 JSON，验证重试逻辑触发

**验收标准**: Self-Planning 生成合法 TaskConfig 的测试通过；非法 JSON 触发重试的测试通过

---

## T30 — 实现完整 CLI 命令集

**对应**: plan-01.md S4-4 + §3.9 M-CLI（全部命令）

**执行步骤**:
1. 在 `cli/task.py` 中实现 `task_app = typer.Typer()`，包含以下命令：
   - `clawtail task list`：扫描 `~/.clawtail/tasks/`，用 rich table 输出 task_id、name、trigger type、trigger value
   - `clawtail task run <task_id>`：调用 `task_scheduler.run_now(task_id)`，实时输出 Agent 执行步骤（每次 tool call 打印一行）
   - `clawtail task show <task_id>`：加载并 pretty-print Task JSON
   - `clawtail task validate <path>`：调用 `validate_task`，输出验证结果
   - `clawtail task generate "<goal>"`：调用 `SelfPlanner.plan(goal)`，输出生成的 Task JSON 路径，询问用户是否立即执行
2. 在 `cli/log.py` 中实现 `log_app = typer.Typer()`：
   - `clawtail log list`：扫描 `~/.clawtail/logs/runs/`，输出最近 20 条运行记录（task_id、run_id、status、started_at、duration）
   - `clawtail log show <run_id>`：加载并格式化输出完整 AgentRunResult（含 tool_calls 列表）
3. 完善 `clawtail start` 命令：
   - 调用 `init_storage()`
   - 调用 `get_env_profile()`（输出检测结果）
   - 启动 `PollManager`
   - 启动 Webhook Server
   - 启动所有 MCP Tool Server 子进程
   - 调用 `task_scheduler.load_tasks()` 并 `start()`
   - 输出 "✅ ClawWithTail started. Press Ctrl+C to stop."
   - 阻塞等待，Ctrl+C 时优雅关闭所有组件
4. 编写 `tests/unit/test_cli.py`：使用 Typer 的 `CliRunner`，测试 `clawtail task list` 输出包含示例 task；`clawtail task validate` 对合法 JSON 输出 "✅ Valid"

**验收标准**: `clawtail task list` 输出示例 tasks；`clawtail start` 启动后 `clawtail device list` 可用；`clawtail log list` 输出运行历史
