"""
Device Data Bus — Webhook Server (Push path).

Sensors that support push mode POST their readings to:
    POST http://127.0.0.1:17171/webhook/{device_id}

Body: {"value": <float>, "unit": "<string>", "meta": {<optional>}}

The server validates that device_id is registered in devices_config,
constructs a BusMessage, and puts it into the bus.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.models.bus import BusMessage, BusPayload

# Module-level imports for mockability in tests
from core.config import devices_config
from core.bus.bus import DeviceDataBus

# Lazy bus reference — resolved at request time to avoid circular import at module load
bus: DeviceDataBus | None = None


def _get_bus() -> DeviceDataBus:
    global bus
    if bus is None:
        from core.bus import bus as _bus
        bus = _bus
    return bus

logger = logging.getLogger(__name__)

# FastAPI app — imported by start_webhook_server()
app = FastAPI(title="ClawWithTail Device Webhook", docs_url=None, redoc_url=None)


class PushPayload(BaseModel):
    value: float
    unit: str = ""
    meta: dict = {}


@app.post("/webhook/{device_id}")
async def receive_push(device_id: str, payload: PushPayload, request: Request) -> JSONResponse:
    """Receive a push notification from a sensor device."""
    # Validate device_id is registered
    registered_ids = {d.id for d in devices_config.devices}
    if device_id not in registered_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Device '{device_id}' is not registered in devices.yaml",
        )

    msg = BusMessage(
        device_id=device_id,
        device_type="sensor",
        timestamp=datetime.now(tz=timezone.utc),
        payload=BusPayload(
            type="reading",
            data=payload.value,
            unit=payload.unit,
            meta=payload.meta,
        ),
    )
    await _get_bus().put(msg)
    logger.info("Webhook: received push from %s: %s %s", device_id, payload.value, payload.unit)

    # Fire internal event (event_bus integrated in Sprint 2/T22)
    # For now, just log
    return JSONResponse({"status": "ok"})


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _check_port_available(host: str, port: int) -> None:
    """Raise a RuntimeError with a friendly message if the port is already in use."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            raise RuntimeError(
                f"Port {port} is already in use on {host}.\n"
                f"  → A previous 'clawtail start' may still be running in the background.\n"
                f"  → On Windows, run:  netstat -ano | findstr :{port}\n"
                f"    then kill the process with:  taskkill /PID <pid> /F\n"
                f"  → Or change the webhook port in config/config.yaml: bus.webhook_port"
            )


async def start_webhook_server(host: str = "127.0.0.1", port: int = 17171) -> asyncio.Task:
    """
    Start the Webhook server as a background asyncio task.

    Returns the asyncio.Task so the caller can cancel it on shutdown.
    Raises RuntimeError with a friendly message if the port is already in use.
    """
    import uvicorn

    # Check port availability before starting uvicorn (gives a clear error message)
    _check_port_available(host, port)

    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    task = asyncio.create_task(server.serve(), name="webhook_server")
    logger.info("Webhook server starting on %s:%d", host, port)
    return task
