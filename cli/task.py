"""
cli.task — Task management CLI commands.

Commands:
  clawtail task list                  — list all configured tasks
  clawtail task run <task_id>         — manually trigger a task run
  clawtail task show <task_id>        — show task config JSON
  clawtail task validate <path>       — validate a Task JSON file
  clawtail task generate "<goal>"     — LLM-assisted task generation
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

task_app = typer.Typer(help="Task management commands")
console = Console()


@task_app.command("list")
def task_list() -> None:
    """List all configured tasks."""
    from core.config import app_config
    from core.task_runner.loader import load_task, TaskLoadError

    base_dir = Path(app_config.storage.base_dir).expanduser()
    tasks_dir = base_dir / "tasks"

    if not tasks_dir.exists():
        console.print(f"[yellow]No tasks directory found at {tasks_dir}[/yellow]")
        console.print("[dim]Create tasks in ~/.clawtail/tasks/ or use 'clawtail task generate'[/dim]")
        return

    json_files = sorted(tasks_dir.glob("*.json"))
    if not json_files:
        console.print("[yellow]No tasks found.[/yellow]")
        return

    table = Table(title="Configured Tasks", show_header=True)
    table.add_column("task_id", style="bold cyan", no_wrap=True)
    table.add_column("name", style="white")
    table.add_column("trigger", style="green")
    table.add_column("value", style="dim")
    table.add_column("description", style="dim")

    for json_file in json_files:
        try:
            task = load_task(json_file)
            trigger_value = task.trigger.cron or task.trigger.event or "manual"
            table.add_row(
                task.task_id,
                task.name,
                task.trigger.type,
                trigger_value,
                task.description[:60] + ("..." if len(task.description) > 60 else ""),
            )
        except TaskLoadError as exc:
            table.add_row(
                json_file.stem, "[red]INVALID[/red]", "-", "-", str(exc)[:60]
            )

    console.print(table)


@task_app.command("run")
def task_run(task_id: str = typer.Argument(..., help="Task ID to run")) -> None:
    """Manually trigger a task run and stream the output."""
    async def _run():
        from core.scheduler import get_task_scheduler
        from core.task_runner.runner import get_task_runner

        scheduler = get_task_scheduler()
        # Load tasks first
        scheduler.load_tasks()

        # Start MCP tool servers so the LLM has tools available
        runner = get_task_runner()
        await runner.start()

        console.print(f"[bold green]Running task:[/bold green] {task_id}")
        console.print("[dim]Streaming tool calls...[/dim]\n")

        try:
            result = await scheduler.run_now(task_id)
        except KeyError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1)
        finally:
            await runner.stop()

        # Print tool call summary
        if result.tool_calls:
            table = Table(title="Tool Calls", show_header=True)
            table.add_column("#", style="dim", width=4)
            table.add_column("Tool", style="cyan")
            table.add_column("Duration", style="dim")
            table.add_column("Result (snippet)", style="white")
            for i, tc in enumerate(result.tool_calls, 1):
                result_snippet = str(tc.output)[:80] + ("..." if len(str(tc.output)) > 80 else "")
                table.add_row(str(i), tc.tool_name, f"{tc.duration_ms}ms", result_snippet)
            console.print(table)

        # Print final summary
        status_color = "green" if result.status == "success" else "yellow" if result.status == "step_limit_reached" else "red"
        console.print(f"\n[bold {status_color}]Status:[/bold {status_color}] {result.status}")
        if result.final_summary:
            console.print(f"\n[bold]Final Summary:[/bold]\n{result.final_summary}")
        if result.report_path:
            console.print(f"\n[dim]Report saved:[/dim] {result.report_path}")
        if result.notification_sent:
            console.print("[green]✓ Feishu notification sent[/green]")
        if result.error:
            console.print(f"[red]Error:[/red] {result.error}")

    asyncio.run(_run())


@task_app.command("show")
def task_show(task_id: str = typer.Argument(..., help="Task ID to show")) -> None:
    """Show the full Task JSON configuration."""
    from core.config import app_config
    from core.task_runner.loader import load_task, TaskLoadError

    base_dir = Path(app_config.storage.base_dir).expanduser()
    task_file = base_dir / "tasks" / f"{task_id}.json"

    if not task_file.exists():
        console.print(f"[red]Task not found:[/red] {task_id}")
        raise typer.Exit(1)

    try:
        task = load_task(task_file)
        task_json = json.dumps(task.to_dict(), ensure_ascii=False, indent=2)
        syntax = Syntax(task_json, "json", theme="monokai", line_numbers=True)
        console.print(syntax)
    except TaskLoadError as exc:
        console.print(f"[red]Failed to load task:[/red] {exc}")
        raise typer.Exit(1)


@task_app.command("validate")
def task_validate(
    path: str = typer.Argument(..., help="Path to Task JSON file")
) -> None:
    """Validate a Task JSON file against the schema."""
    from core.task_runner.validator import validate_task

    task_path = Path(path)
    if not task_path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(1)

    try:
        raw = json.loads(task_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON:[/red] {exc}")
        raise typer.Exit(1)

    is_valid, errors = validate_task(raw)
    if is_valid:
        console.print(f"[bold green]✅ Valid[/bold green] — {task_path.name}")
    else:
        console.print(f"[bold red]❌ Invalid[/bold red] — {task_path.name}")
        for err in errors:
            console.print(f"  [red]•[/red] {err}")
        raise typer.Exit(1)


@task_app.command("generate")
def task_generate(
    goal: str = typer.Argument(..., help="Natural language goal description"),
    run_now: bool = typer.Option(False, "--run", help="Run the generated task immediately"),
) -> None:
    """Generate a Task configuration using LLM Self-Planning Mode."""
    async def _run():
        from core.agent.self_planner import SelfPlanner

        console.print(f"[bold]Goal:[/bold] {goal}")
        console.print("[dim]Starting Self-Planning agent...[/dim]\n")

        planner = SelfPlanner()
        try:
            await planner.start()
            task_config = await planner.plan(goal)
        finally:
            await planner.stop()

        from core.config import app_config
        task_file = Path(app_config.storage.base_dir).expanduser() / "tasks" / f"{task_config.task_id}.json"
        console.print(f"[bold green]✅ Task generated:[/bold green] {task_config.task_id}")
        console.print(f"[dim]Saved to:[/dim] {task_file}")
        console.print(f"\n[bold]Name:[/bold] {task_config.name}")
        console.print(f"[bold]Trigger:[/bold] {task_config.trigger.type} — {task_config.trigger.cron or task_config.trigger.event or 'manual'}")
        console.print(f"[bold]Goal:[/bold] {task_config.goal[:200]}")

        if run_now:
            console.print("\n[bold]Running task now...[/bold]")
            from core.scheduler import get_task_scheduler
            scheduler = get_task_scheduler()
            scheduler.register_task(task_config)
            result = await scheduler.run_now(task_config.task_id)
            console.print(f"[bold]Status:[/bold] {result.status}")

    asyncio.run(_run())
