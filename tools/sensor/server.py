"""
tools.sensor.server — sensor MCP Tool Package.

Provides tools for reading sensor data from the Device Data Bus.

Tools:
  sensor.list_devices    — list all registered sensor devices and their status
  sensor.read_latest     — read the most recent value for a device
  sensor.read_history    — read historical values for a time range
  sensor.get_stats       — compute statistics over a time window
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

from tools.shared.errors import NoDataError, DeviceNotFoundError

logger = logging.getLogger(__name__)

app = Server("sensor-tools")


# ── Tool definitions ──────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sensor.list_devices",
            description="List all registered sensor devices and their data availability status.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="sensor.read_latest",
            description="Read the most recent sensor value for a device from the data bus.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "The device ID to read from (e.g. 'lab_temp_sensor')",
                    }
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="sensor.read_history",
            description="Read historical sensor values for a device within a time range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "from_iso": {
                        "type": "string",
                        "description": "Start time in ISO 8601 format (e.g. '2026-01-01T00:00:00+00:00')",
                    },
                    "to_iso": {
                        "type": "string",
                        "description": "End time in ISO 8601 format",
                    },
                },
                "required": ["device_id", "from_iso", "to_iso"],
            },
        ),
        Tool(
            name="sensor.get_stats",
            description=(
                "Compute statistics (min, max, avg, trend) for a sensor device "
                "over a specified time range."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "from_iso": {"type": "string"},
                    "to_iso": {"type": "string"},
                },
                "required": ["device_id", "from_iso", "to_iso"],
            },
        ),
    ]


# ── Tool handlers ─────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "sensor.list_devices":
            result = await _list_devices()
        elif name == "sensor.read_latest":
            result = await _read_latest(arguments["device_id"])
        elif name == "sensor.read_history":
            result = await _read_history(
                arguments["device_id"],
                arguments["from_iso"],
                arguments["to_iso"],
            )
        elif name == "sensor.get_stats":
            result = await _get_stats(
                arguments["device_id"],
                arguments["from_iso"],
                arguments["to_iso"],
            )
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except (NoDataError, DeviceNotFoundError) as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    except Exception as exc:
        logger.exception("sensor tool error in %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ── Implementation ────────────────────────────────────────────────────────────

async def _list_devices() -> list[dict]:
    from core.config import devices_config
    from core.bus import bus

    result = []
    for device in devices_config.devices:
        if device.type != "sensor":
            continue
        latest = await bus.get_latest(device.id)
        result.append({
            "device_id": device.id,
            "subtype": device.subtype or "unknown",
            "transport": device.transport,
            "status": "active" if latest is not None else "no_data",
        })
    return result


async def _read_latest(device_id: str) -> dict:
    from core.config import devices_config
    from core.bus import bus

    # Validate device exists
    registered = {d.id for d in devices_config.devices if d.type == "sensor"}
    if device_id not in registered:
        raise DeviceNotFoundError(
            f"Device '{device_id}' not found in devices.yaml",
            tool_name="sensor.read_latest",
        )

    msg = await bus.get_latest(device_id)
    if msg is None:
        raise NoDataError(
            f"No data available for device '{device_id}'",
            tool_name="sensor.read_latest",
        )

    return {
        "value": msg.payload.data,
        "unit": msg.payload.unit or "",
        "timestamp": msg.timestamp.isoformat(),
    }


async def _read_history(device_id: str, from_iso: str, to_iso: str) -> list[dict]:
    from core.bus import bus

    messages = bus.get_history(device_id, from_iso, to_iso)
    return [
        {
            "value": m.payload.data,
            "unit": m.payload.unit or "",
            "timestamp": m.timestamp.isoformat(),
        }
        for m in messages
        if m.payload.type == "reading"
    ]


async def _get_stats(device_id: str, from_iso: str, to_iso: str) -> dict:
    from core.bus import bus

    messages = bus.get_history(device_id, from_iso, to_iso)
    readings = [
        float(m.payload.data)
        for m in messages
        if m.payload.type == "reading" and isinstance(m.payload.data, (int, float))
    ]
    unit = next(
        (m.payload.unit for m in messages if m.payload.type == "reading"),
        None,
    )

    if not readings:
        return {
            "device_id": device_id,
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "trend": "insufficient_data",
            "unit": unit,
        }

    avg = sum(readings) / len(readings)

    # Trend: compare first 1/3 vs last 1/3
    trend = "insufficient_data"
    if len(readings) >= 3:
        third = max(1, len(readings) // 3)
        first_avg = sum(readings[:third]) / third
        last_avg = sum(readings[-third:]) / third
        if first_avg != 0:
            diff_pct = (last_avg - first_avg) / abs(first_avg)
            if diff_pct > 0.05:
                trend = "rising"
            elif diff_pct < -0.05:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "stable"

    return {
        "device_id": device_id,
        "count": len(readings),
        "min": min(readings),
        "max": max(readings),
        "avg": round(avg, 3),
        "trend": trend,
        "unit": unit,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from tools.shared.mcp_base import run_server
    asyncio.run(run_server(app))
