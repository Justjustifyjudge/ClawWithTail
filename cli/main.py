"""
ClawWithTail CLI — main entry point.
Built with Typer. Registered as `clawtail` in pyproject.toml.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="clawtail",
    help="ClawWithTail — Physical World AI Agent Platform",
    no_args_is_help=True,
)
console = Console()

# ── Sub-command groups ─────────────────────────────────────────────────────────
env_app = typer.Typer(help="Environment detection commands")
app.add_typer(env_app, name="env")

from cli.device import device_app  # noqa: E402
app.add_typer(device_app, name="device")

from cli.task import task_app  # noqa: E402
app.add_typer(task_app, name="task")

from cli.log import log_app  # noqa: E402
app.add_typer(log_app, name="log")


# ── env commands ──────────────────────────────────────────────────────────────

@env_app.command("show")
def env_show() -> None:
    """Show the detected environment profile (cached after first run)."""
    from env.state import get_env_profile
    profile = get_env_profile()
    _print_env_profile(profile)


@env_app.command("check")
def env_check() -> None:
    """Re-run environment detection and show the updated profile."""
    from env.state import reset_env_profile, get_env_profile
    reset_env_profile()
    profile = get_env_profile()
    console.print("[bold green]Environment re-detected[/bold green]")
    _print_env_profile(profile)


# ── start command ─────────────────────────────────────────────────────────────

@app.command("start")
def start() -> None:
    """Start the ClawWithTail daemon (bus + scheduler + MCP servers)."""
    import asyncio

    async def _run():
        from core.storage_init import init_storage
        from core.config import app_config
        from core.bus import bus, poll_manager
        from core.bus.webhook_server import start_webhook_server
        from core.scheduler import get_task_scheduler
        from env.state import get_env_profile

        # 1. Init storage
        root = init_storage(app_config.storage.base_dir)

        # 2. Detect environment
        profile = get_env_profile()
        console.print(f"[bold green]ClawWithTail starting...[/bold green]")
        console.print(f"   OS             : [cyan]{profile.os}[/cyan]")
        console.print(f"   GPU            : [cyan]{profile.gpu_type}[/cyan]")
        console.print(f"   YOLO variant   : [cyan]{profile.yolo_variant}[/cyan]")
        console.print(f"   Data directory : [cyan]{root}[/cyan]")

        # 3. Start webhook server
        try:
            webhook_task = await start_webhook_server(
                host="127.0.0.1",
                port=app_config.bus.webhook_port,
            )
        except RuntimeError as exc:
            console.print(f"\n[bold red]❌ Failed to start webhook server:[/bold red]\n{exc}")
            raise typer.Exit(code=1)
        console.print(
            f"   Webhook server : [cyan]http://127.0.0.1:{app_config.bus.webhook_port}[/cyan]"
        )

        # 4. Start poll manager
        poll_manager.start()
        console.print("   Poll manager   : [cyan]started[/cyan]")

        # 5. Start task runner MCP servers
        from core.task_runner.runner import get_task_runner
        runner = get_task_runner()
        try:
            await runner.start()
            console.print("   MCP servers    : [cyan]started[/cyan]")
        except Exception as exc:
            console.print(f"   MCP servers    : [yellow]partial start ({exc})[/yellow]")

        # 6. Load tasks and start scheduler
        scheduler = get_task_scheduler()
        n_tasks = scheduler.load_tasks()
        scheduler.start()
        console.print(f"   Scheduler      : [cyan]started ({n_tasks} task(s) loaded)[/cyan]")

        console.print(
            "\n[bold green]✅ ClawWithTail started.[/bold green] "
            "[dim]Press Ctrl+C to stop.[/dim]"
        )

        try:
            await asyncio.gather(webhook_task)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            console.print("\n[yellow]Shutting down...[/yellow]")
            scheduler.stop()
            poll_manager.stop()
            webhook_task.cancel()
            await runner.stop()
            console.print("[yellow]ClawWithTail stopped.[/yellow]")

    asyncio.run(_run())


@app.command("stop")
def stop() -> None:
    """Stop the ClawWithTail daemon."""
    console.print("[yellow]ClawWithTail stopped.[/yellow]")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_env_profile(profile) -> None:
    table = Table(title="ClawWithTail — Environment Profile", show_header=True)
    table.add_column("Field", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("os", profile.os)
    table.add_row("camera_backend", profile.camera_backend)
    table.add_row("gpu_available", str(profile.gpu_available))
    table.add_row("gpu_type", profile.gpu_type)
    table.add_row("bluetooth_available", str(profile.bluetooth_available))
    table.add_row("python_version", profile.python_version)
    table.add_row("yolo_variant", profile.yolo_variant)
    table.add_row(
        "detected_cameras",
        ", ".join(f"{c['id']}:{c['name']}" for c in profile.detected_cameras) or "none",
    )
    table.add_row(
        "detected_serial_ports",
        ", ".join(profile.detected_serial_ports) or "none",
    )
    console.print(table)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
