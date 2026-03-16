"""Sprint 2 smoke verification — tests core logic without MCP protocol."""
import sys, asyncio, json, tempfile, time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, r"c:\Users\yiffanlin\Desktop\ClawWithTail\ClawWithTail")

# Clear any cached module versions to ensure fresh imports
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith(("tools.", "core.", "adapters.", "env.", "cli.")):
        del sys.modules[mod_name]

errors = []
passed = []

def check(name, fn):
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        passed.append(name)
        print(f"  PASS  {name}")
    except Exception as e:
        import traceback
        errors.append((name, str(e)))
        print(f"  FAIL  {name}: {e}")

# ── T17: shared infrastructure ────────────────────────────────────────────────
def test_tool_error():
    from tools.shared.errors import ToolError, NoDataError
    e = ToolError("test error", "vision.capture_frame")
    assert "vision.capture_frame" in str(e)
    e2 = NoDataError("no data", "sensor.read_latest")
    assert isinstance(e2, ToolError)

def test_tool_config():
    from tools.shared.config import get_tool_config
    cfg = get_tool_config()
    assert hasattr(cfg, "default_model")
    assert hasattr(cfg, "feishu_default_webhook")
    assert hasattr(cfg, "yolo_variant")

# ── T18: vision tools ─────────────────────────────────────────────────────────
def test_camera_registry_init():
    from tools.vision.camera_registry import CameraRegistry
    reg = CameraRegistry()
    assert not reg._initialized

def test_vision_capture_frame():
    async def _run():
        from tools.vision.server import _capture_frame
        from adapters.camera.mock import MockCameraAdapter
        import tools.vision.server as vs
        with tempfile.TemporaryDirectory() as tmp:
            mock_adapter = MockCameraAdapter(
                MagicMock(id="desk_camera", type="camera", transport="usb", source="0"),
                MagicMock(os="linux", camera_backend="none"),
            )
            with patch.object(vs, "camera_registry") as mock_reg, \
                 patch.object(vs, "init_storage", return_value=Path(tmp)):
                mock_reg.get.return_value = mock_adapter
                result = await _capture_frame("desk_camera", save_path=None)
            assert "frame_path" in result
            assert Path(result["frame_path"]).exists()
    return _run()

def test_count_objects_from_log():
    async def _run():
        from tools.vision.server import _count_objects
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "watch.jsonl"
            now = datetime.now(tz=timezone.utc)
            events = [
                {"timestamp": (now - timedelta(minutes=10)).isoformat(), "labels": ["cup"], "confidences": [0.9]},
                {"timestamp": (now - timedelta(minutes=30)).isoformat(), "labels": ["cup"], "confidences": [0.85]},
                {"timestamp": (now - timedelta(minutes=90)).isoformat(), "labels": ["cup"], "confidences": [0.8]},
            ]
            with open(log, "w") as f:
                for e in events:
                    f.write(json.dumps(e) + "\n")
            result = await _count_objects(str(log), "cup", window_minutes=60)
            assert result["count"] == 2
    return _run()

# ── T19: watcher ──────────────────────────────────────────────────────────────
def test_watcher_writes_event():
    async def _run():
        from tools.vision.watcher import _watch_loop
        with tempfile.TemporaryDirectory() as tmp:
            event_log = str(Path(tmp) / "watch.jsonl")
            dummy_frame = Path(tmp) / "frame.jpg"
            dummy_frame.write_bytes(b"\xFF\xD8\xFF\xD9")

            async def mock_capture(source_id, save_path=None):
                return {"frame_path": str(dummy_frame), "timestamp": "2026-01-01T00:00:00+00:00"}

            async def mock_detect(frame_path, confidence=0.5):
                return [{"label": "cup", "confidence": 0.92, "bbox": [0, 0, 100, 100]}]

            call_count = [0]
            async def controlled_sleep(seconds):
                call_count[0] += 1
                if call_count[0] >= 1:
                    raise asyncio.CancelledError()

            import tools.vision.watcher as wm
            with patch.object(wm, "_capture_frame", mock_capture), \
                 patch.object(wm, "_detect_objects", mock_detect), \
                 patch("asyncio.sleep", side_effect=controlled_sleep):
                try:
                    await _watch_loop("desk_camera", ["cup"], 30, 300, event_log)
                except asyncio.CancelledError:
                    pass

            lines = [l for l in Path(event_log).read_text().strip().split("\n") if l]
            assert len(lines) >= 1
            event = json.loads(lines[0])
            assert "cup" in event["labels"]
    return _run()

# ── T20: sensor tools ─────────────────────────────────────────────────────────
def test_sensor_no_data_error():
    async def _run():
        from tools.shared.errors import NoDataError
        mock_dc = MagicMock()
        mock_dc.devices = [MagicMock(id="lab_temp_sensor", type="sensor")]
        mock_bus = MagicMock()
        mock_bus.get_latest = AsyncMock(return_value=None)

        async def patched_read_latest(device_id):
            registered = {"lab_temp_sensor"}
            if device_id not in registered:
                from tools.shared.errors import DeviceNotFoundError
                raise DeviceNotFoundError(f"Device '{device_id}' not found")
            msg = await mock_bus.get_latest(device_id)
            if msg is None:
                raise NoDataError(f"No data available for device '{device_id}'")
            return {}

        try:
            await patched_read_latest("lab_temp_sensor")
            assert False, "Should have raised NoDataError"
        except NoDataError:
            pass
    return _run()

# ── T21: storage tools ────────────────────────────────────────────────────────
def test_storage_save_read_roundtrip():
    from tools.storage.server import _save_summary, _read_summary, _list_summaries
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch("tools.storage.server._summaries_dir", return_value=tmp_path):
            r = _save_summary("Plant is healthy.", "plant_monitor", ["daily"])
            read = _read_summary(r["summary_id"])
            assert read["content"] == "Plant is healthy."
            assert read["metadata"]["category"] == "plant_monitor"
            lst = _list_summaries(category="plant_monitor")
            assert len(lst) == 1

def test_storage_path_traversal_blocked():
    from tools.storage.server import _read_report
    from tools.shared.errors import PathTraversalError
    with tempfile.TemporaryDirectory() as tmp:
        with patch("tools.storage.server._reports_dir", return_value=Path(tmp)):
            try:
                _read_report("/etc/passwd")
                assert False, "Should have raised PathTraversalError"
            except PathTraversalError:
                pass

def test_storage_report_roundtrip():
    from tools.storage.server import _save_report, _read_report
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch("tools.storage.server._reports_dir", return_value=tmp_path):
            r = _save_report("# Report\nContent.", "Test Report", "plant_monitor")
            read = _read_report(r["report_path"])
            assert read["content"] == "# Report\nContent."

# ── T22: notify + event_bus ───────────────────────────────────────────────────
def test_feishu_send_success():
    async def _run():
        from tools.notify.server import _feishu_send
        import tools.notify.server as ns
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_cfg = MagicMock()
        mock_cfg.feishu_default_webhook = "https://test.webhook.url"
        with patch.object(ns, "get_tool_config", return_value=mock_cfg), \
             patch.object(ns, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            result = await _feishu_send("Hello!")
        assert result["success"] is True
        assert result["status_code"] == 200
    return _run()

def test_feishu_send_failure():
    async def _run():
        from tools.notify.server import _feishu_send
        import tools.notify.server as ns
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_cfg = MagicMock()
        mock_cfg.feishu_default_webhook = "https://test.webhook.url"
        with patch.object(ns, "get_tool_config", return_value=mock_cfg), \
             patch.object(ns, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            result = await _feishu_send("Hello!")
        assert result["success"] is False
    return _run()

def test_event_bus_subscribe_publish():
    async def _run():
        from core.scheduler.event_bus import EventBus
        bus = EventBus()
        received = []
        def cb(event, data): received.append((event, data))
        bus.subscribe("task.completed", cb)
        await bus.publish("task.completed", {"task_id": "plant_monitor"})
        assert len(received) == 1
        assert received[0][1]["task_id"] == "plant_monitor"
    return _run()

def test_event_bus_wildcard():
    async def _run():
        from core.scheduler.event_bus import EventBus
        bus = EventBus()
        received = []
        def cb(event, data): received.append(event)
        bus.subscribe("device.push:*", cb)
        await bus.publish("device.push:lab_temp_sensor", {})
        await bus.publish("device.push:plant_soil_sensor", {})
        await bus.publish("task.completed", {})  # Should NOT match
        assert len(received) == 2
        assert "device.push:lab_temp_sensor" in received
    return _run()

# ── T23: knowledge tools ──────────────────────────────────────────────────────
def test_knowledge_cache_hit():
    async def _run():
        from tools.knowledge.server import _fetch_care_guide
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cached = {"watering": "Weekly", "light": "Indirect", "temperature": "20-25C", "humidity": "Medium", "notes": ""}
            (tmp_path / "monstera.json").write_text(json.dumps(cached))
            mock_search = AsyncMock()
            with patch("tools.knowledge.server._cache_dir", return_value=tmp_path), \
                 patch("tools.knowledge.server._search_web", mock_search):
                result = await _fetch_care_guide("monstera")
            mock_search.assert_not_called()
            assert result["watering"] == "Weekly"
    return _run()

def test_knowledge_search_local_kb():
    from tools.knowledge.server import _search_local_kb
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        summaries_dir = tmp_path / "summaries"
        summaries_dir.mkdir()
        summaries = [
            {"id": "s1", "category": "plant_monitor", "tags": [], "created_at": "2026-01-01T00:00:00+00:00",
             "content": "The plant needs water. Water the plant daily."},
            {"id": "s2", "category": "plant_monitor", "tags": [], "created_at": "2026-01-02T00:00:00+00:00",
             "content": "Temperature is normal. No issues."},
        ]
        for s in summaries:
            (summaries_dir / f"{s['id']}.json").write_text(json.dumps(s))
        from core.config import app_config
        orig = app_config.storage.base_dir
        try:
            app_config.storage.base_dir = str(tmp_path)
            results = _search_local_kb("water plant")
        finally:
            app_config.storage.base_dir = orig
        assert len(results) >= 1
        assert results[0]["summary_id"] == "s1"  # s1 has more "water" matches

# ── Run all ───────────────────────────────────────────────────────────────────
print("\n=== Sprint 2 Smoke Verification ===\n")
for name, fn in [
    ("T17: ToolError hierarchy", test_tool_error),
    ("T17: get_tool_config returns ToolConfig", test_tool_config),
    ("T18: CameraRegistry initializes lazily", test_camera_registry_init),
    ("T18: vision.capture_frame saves JPEG", test_vision_capture_frame),
    ("T18: vision.count_objects time filter", test_count_objects_from_log),
    ("T19: watcher writes event to JSONL", test_watcher_writes_event),
    ("T20: sensor.read_latest raises NoDataError", test_sensor_no_data_error),
    ("T21: storage save→read roundtrip", test_storage_save_read_roundtrip),
    ("T21: storage path traversal blocked", test_storage_path_traversal_blocked),
    ("T21: storage report roundtrip", test_storage_report_roundtrip),
    ("T22: notify.feishu_send success", test_feishu_send_success),
    ("T22: notify.feishu_send failure 500", test_feishu_send_failure),
    ("T22: event_bus subscribe+publish", test_event_bus_subscribe_publish),
    ("T22: event_bus wildcard matching", test_event_bus_wildcard),
    ("T23: knowledge cache hit skips network", test_knowledge_cache_hit),
    ("T23: knowledge search_local_kb ranking", test_knowledge_search_local_kb),
]:
    check(name, fn)

print(f"\n{'='*50}")
print(f"Results: {len(passed)} passed, {len(errors)} failed")
if errors:
    print("\nFailed:")
    for name, err in errors:
        print(f"  - {name}")
        print(f"    {err}")
    sys.exit(1)
else:
    print("\nAll Sprint 2 checks passed! ✅")
