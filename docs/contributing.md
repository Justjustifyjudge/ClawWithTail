# Contributing to ClawWithTail

Thank you for contributing! This guide covers the three main extension scenarios.

---

## 1. Adding a New MCP Tool Package

MCP Tool Packages live in `tools/`. Each package is a standalone FastAPI + MCP server.

**Reference implementation**: `tools/vision/` (most complete example)

### Steps

1. **Create the package directory**:
   ```
   tools/my_tool/
   ├── __init__.py
   └── server.py
   ```

2. **Implement `server.py`** following the vision pattern:
   ```python
   from mcp.server.fastmcp import FastMCP
   from tools.shared.mcp_base import create_mcp_server, run_server
   from tools.shared.errors import ToolError

   mcp = create_mcp_server("my_tool")

   @mcp.tool()
   async def my_action(param: str) -> dict:
       """Tool description shown to the LLM."""
       # ... implementation
       return {"result": "..."}

   if __name__ == "__main__":
       run_server(mcp)
   ```

3. **Register in `TaskRunner.start()`** (`core/task_runner/runner.py`):
   ```python
   ("my_tool", [sys.executable, "-m", "tools.my_tool.server"]),
   ```

4. **Write unit tests** in `tests/unit/test_my_tool.py`:
   - Mock all external calls (HTTP, filesystem, LLM)
   - Test each tool function independently
   - Test error cases (invalid input, network failure)

5. **Add integration test** in `tests/integration/test_my_tool.py`:
   - Test the full tool call flow via mock MCP transport

### Conventions

- All tool functions must be `async`
- Return `dict` (will be JSON-serialized for the LLM)
- Raise `ToolError` subclasses for expected errors
- Use `get_tool_config()` from `tools/shared/config.py` for configuration
- Never return raw image bytes — return file paths instead

---

## 2. Adding a New Device Adapter

Device adapters live in `adapters/`. There are two types: camera and sensor.

### Camera Adapter

**Reference**: `adapters/camera/v4l2.py`

1. **Create** `adapters/camera/my_platform.py`:
   ```python
   from adapters.camera.base import CameraAdapter

   class MyPlatformCamera(CameraAdapter):
       def __init__(self, source_id: str | int = 0) -> None:
           self._source_id = source_id

       def capture_frame(self) -> bytes:
           """Capture a single frame and return JPEG bytes."""
           # ... implementation using platform-specific API
           return jpeg_bytes

       def release(self) -> None:
           """Release camera resources."""
           pass
   ```

2. **Register in factory** (`adapters/camera/__init__.py`):
   ```python
   elif sys.platform == "my_platform":
       from adapters.camera.my_platform import MyPlatformCamera
       return MyPlatformCamera(source_id)
   ```

3. **Write tests** — mock the platform API, test JPEG output validity.

### Sensor Adapter

**Reference**: `adapters/sensor/wifi_poll.py`

1. **Create** `adapters/sensor/my_protocol.py`:
   ```python
   from adapters.sensor.base import SensorAdapter
   from core.models.bus import BusMessage

   class MyProtocolAdapter(SensorAdapter):
       def __init__(self, device_config) -> None:
           self._config = device_config

       async def read(self) -> BusMessage:
           """Read sensor value and return BusMessage."""
           # ... implementation
           return BusMessage(
               device_id=self._config.device_id,
               payload={"value": value, "unit": unit},
           )
   ```

2. **Register in factory** (`adapters/sensor/__init__.py`):
   ```python
   elif config.protocol == "my_protocol":
       from adapters.sensor.my_protocol import MyProtocolAdapter
       return MyProtocolAdapter(config)
   ```

3. **Write tests** — mock the protocol, test BusMessage output.

---

## 3. Adding a New Notification Channel

Notification tools live in `tools/notify/server.py`.

1. **Add a new tool function**:
   ```python
   @mcp.tool()
   async def telegram_send(message: str, chat_id: str = "") -> dict:
       """Send a Telegram message."""
       cfg = get_tool_config()
       token = os.environ.get(cfg.notify.telegram_token_env, "")
       if not token:
           raise NotifyError("TELEGRAM_BOT_TOKEN not set")
       # ... httpx call to Telegram API
       return {"success": True}
   ```

2. **Add configuration** in `core/config/models.py` → `NotifyConfig`:
   ```python
   telegram_token_env: str = "TELEGRAM_BOT_TOKEN"
   ```

3. **Add to `.env.example`**:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```

4. **Write tests** — mock `httpx.AsyncClient.post`, test success and failure cases.

---

## Code Style

| Rule | Tool |
|---|---|
| Formatting | `black` (line length 100) |
| Import sorting | `isort` |
| Type annotations | Required on all public functions |
| Docstrings | Required on all public classes and functions |
| Async | All I/O must be `async` |

Run before committing:
```bash
black . && isort . && mypy core/ tools/ adapters/ cli/
```

---

## Testing

```bash
# Unit tests only (fast, no hardware)
pytest tests/unit/ -v

# Integration tests (mock hardware)
pytest tests/integration/ -v

# Full test suite
pytest tests/ -v --tb=short
```

All tests must pass before submitting a PR. New features require:
- At least one unit test per public function
- At least one integration test for the happy path
- At least one test for the main error case
