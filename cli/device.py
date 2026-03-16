"""
CLI device command group — `clawtail device list` and `clawtail device test`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

device_app = typer.Typer(help="Device management commands")
console = Console()


@device_app.command("list")
def device_list() -> None:
    """List all registered devices and their availability status."""
    from core.config import devices_config
    from env.state import get_env_profile
    from adapters.camera import get_camera_adapter
    from adapters.sensor import get_sensor_adapter

    profile = get_env_profile()

    table = Table(title="Registered Devices", show_header=True)
    table.add_column("device_id", style="bold cyan", no_wrap=True)
    table.add_column("type", style="white")
    table.add_column("transport", style="white")
    table.add_column("source / url", style="dim")
    table.add_column("status", style="white")

    for device in devices_config.devices:
        try:
            if device.type == "camera":
                adapter = get_camera_adapter(device, profile)
                available = adapter.is_available()
            else:
                # Skip wifi_push devices (they push to us, not polled)
                if device.transport == "wifi_push":
                    available = None  # N/A
                else:
                    adapter = get_sensor_adapter(device, profile)
                    available = adapter.is_available()
        except Exception:
            available = False

        if available is None:
            status = "[yellow]⬆ push mode[/yellow]"
        elif available:
            status = "[green]✅ available[/green]"
        else:
            status = "[red]❌ unavailable[/red]"

        source_info = device.source or device.poll_url or device.push_webhook_path or "-"
        table.add_row(device.id, device.type, device.transport, source_info, status)

    console.print(table)


@device_app.command("test")
def device_test(device_id: str = typer.Argument(..., help="Device ID to test")) -> None:
    """Test a specific device by capturing a frame or polling a reading."""
    from core.config import devices_config, app_config
    from core.storage_init import init_storage
    from env.state import get_env_profile

    # Find device
    device = next((d for d in devices_config.devices if d.id == device_id), None)
    if device is None:
        console.print(f"[red]Error: Device '{device_id}' not found in devices.yaml[/red]")
        raise typer.Exit(code=1)

    profile = get_env_profile()
    root = init_storage(app_config.storage.base_dir)

    if device.type == "camera":
        _test_camera(device, profile, root)
    else:
        asyncio.run(_test_sensor(device, profile))


def _test_camera(device, profile, root: Path) -> None:
    from adapters.camera import get_camera_adapter
    import time

    adapter = get_camera_adapter(device, profile)
    if not adapter.is_available():
        console.print(f"[red]Camera '{device.id}' is not available[/red]")
        raise typer.Exit(code=1)

    save_path = str(root / "data" / "frames" / f"test_{device.id}_{int(time.time())}.jpg")
    try:
        actual_path = adapter.capture_frame(save_path)
        size = Path(actual_path).stat().st_size
        console.print(f"[green]✅ Frame captured[/green]")
        console.print(f"   Path: [cyan]{actual_path}[/cyan]")
        console.print(f"   Size: [cyan]{size:,} bytes[/cyan]")
    except Exception as exc:
        console.print(f"[red]Capture failed: {exc}[/red]")
        raise typer.Exit(code=1)


async def _test_sensor(device, profile) -> None:
    from adapters.sensor import get_sensor_adapter

    if device.transport == "wifi_push":
        console.print(
            f"[yellow]Device '{device.id}' uses push mode — "
            f"send a POST to /webhook/{device.id} to test[/yellow]"
        )
        return

    try:
        adapter = get_sensor_adapter(device, profile)
        msg = await adapter.poll()
        console.print(f"[green]✅ Sensor reading received[/green]")
        console.print(f"   Device: [cyan]{msg.device_id}[/cyan]")
        console.print(f"   Value:  [cyan]{msg.payload.data} {msg.payload.unit}[/cyan]")
        console.print(f"   Time:   [cyan]{msg.timestamp.isoformat()}[/cyan]")
    except Exception as exc:
        console.print(f"[red]Poll failed: {exc}[/red]")
        raise typer.Exit(code=1)
