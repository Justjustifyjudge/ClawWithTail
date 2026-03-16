"""
cli.log — Run log CLI commands.

Commands:
  clawtail log list              — list recent task runs
  clawtail log show <run_id>     — show full run details
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

log_app = typer.Typer(help="Run log commands")
console = Console()


@log_app.command("list")
def log_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent runs to show"),
) -> None:
    """List recent task runs."""
    from core.config import app_config

    base_dir = Path(app_config.storage.base_dir).expanduser()
    runs_dir = base_dir / "logs" / "runs"

    if not runs_dir.exists():
        console.print("[yellow]No run logs found.[/yellow]")
        return

    # Collect all run JSON files
    run_files = []
    for task_dir in runs_dir.iterdir():
        if task_dir.is_dir():
            for run_file in task_dir.glob("*.json"):
                run_files.append(run_file)

    if not run_files:
        console.print("[yellow]No run logs found.[/yellow]")
        return

    # Load and sort by started_at
    runs = []
    for run_file in run_files:
        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
            runs.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    runs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    runs = runs[:limit]

    table = Table(title=f"Recent Task Runs (last {limit})", show_header=True)
    table.add_column("task_id", style="cyan", no_wrap=True)
    table.add_column("run_id", style="dim", no_wrap=True)
    table.add_column("status", style="white")
    table.add_column("started_at", style="dim")
    table.add_column("duration", style="dim")
    table.add_column("steps", style="dim")

    for run in runs:
        status = run.get("status", "?")
        status_color = "green" if status == "success" else "yellow" if status == "step_limit_reached" else "red"

        # Calculate duration
        started = run.get("started_at", "")
        finished = run.get("finished_at", "")
        duration = "-"
        if started and finished:
            try:
                from datetime import datetime
                s = datetime.fromisoformat(started)
                f = datetime.fromisoformat(finished)
                secs = int((f - s).total_seconds())
                duration = f"{secs}s"
            except ValueError:
                pass

        steps = str(len(run.get("tool_calls", [])))
        run_id_short = run.get("run_id", "?")[:8] + "..."

        table.add_row(
            run.get("task_id", "?"),
            run_id_short,
            f"[{status_color}]{status}[/{status_color}]",
            started[:19].replace("T", " ") if started else "-",
            duration,
            steps,
        )

    console.print(table)


@log_app.command("show")
def log_show(run_id: str = typer.Argument(..., help="Run ID to show")) -> None:
    """Show full details of a task run."""
    from core.config import app_config

    base_dir = Path(app_config.storage.base_dir).expanduser()
    runs_dir = base_dir / "logs" / "runs"

    # Search for the run file
    run_file = None
    for task_dir in runs_dir.iterdir():
        if task_dir.is_dir():
            candidate = task_dir / f"{run_id}.json"
            if candidate.exists():
                run_file = candidate
                break
            # Also try partial match
            for f in task_dir.glob("*.json"):
                if f.stem.startswith(run_id):
                    run_file = f
                    break

    if run_file is None:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise typer.Exit(1)

    try:
        data = json.loads(run_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"[red]Failed to read run log:[/red] {exc}")
        raise typer.Exit(1)

    # Header
    status = data.get("status", "?")
    status_color = "green" if status == "success" else "yellow" if status == "step_limit_reached" else "red"
    console.print(f"\n[bold]Run:[/bold] {data.get('run_id', '?')}")
    console.print(f"[bold]Task:[/bold] {data.get('task_id', '?')}")
    console.print(f"[bold {status_color}]Status:[/bold {status_color}] {status}")
    console.print(f"[bold]Started:[/bold] {data.get('started_at', '-')}")
    console.print(f"[bold]Finished:[/bold] {data.get('finished_at', '-')}")

    if data.get("error"):
        console.print(f"[bold red]Error:[/bold red] {data['error']}")

    # Tool calls
    tool_calls = data.get("tool_calls", [])
    if tool_calls:
        console.print(f"\n[bold]Tool Calls ({len(tool_calls)}):[/bold]")
        table = Table(show_header=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Tool", style="cyan")
        table.add_column("Duration", style="dim")
        table.add_column("Input", style="dim")
        table.add_column("Output (snippet)", style="white")
        for i, tc in enumerate(tool_calls, 1):
            input_str = json.dumps(tc.get("input_args", {}), ensure_ascii=False)[:50]
            output_str = str(tc.get("output", ""))[:80]
            table.add_row(
                str(i),
                tc.get("tool_name", "?"),
                f"{tc.get('duration_ms', 0)}ms",
                input_str,
                output_str,
            )
        console.print(table)

    # Final summary
    if data.get("final_summary"):
        console.print(f"\n[bold]Final Summary:[/bold]")
        console.print(data["final_summary"])

    if data.get("report_path"):
        console.print(f"\n[dim]Report:[/dim] {data['report_path']}")
    if data.get("notification_sent"):
        console.print("[green]✓ Feishu notification was sent[/green]")
