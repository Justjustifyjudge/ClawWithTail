"""
tools.storage.server — storage MCP Tool Package.

Provides tools for persisting and retrieving summaries and reports.

Tools:
  storage.save_summary    — save an AI-generated summary to disk
  storage.read_summary    — read a summary by ID
  storage.list_summaries  — list summaries with optional filters
  storage.save_report     — save a Markdown report to disk
  storage.read_report     — read a Markdown report (with path traversal protection)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

from tools.shared.errors import ToolError, PathTraversalError

logger = logging.getLogger(__name__)

app = Server("storage-tools")


# ── Tool definitions ──────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="storage.save_summary",
            description="Save an AI-generated summary with metadata to persistent storage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Summary text content"},
                    "category": {
                        "type": "string",
                        "description": "Category tag (e.g. 'plant_monitor', 'chemistry_monitor')",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of tags",
                    },
                },
                "required": ["content", "category"],
            },
        ),
        Tool(
            name="storage.read_summary",
            description="Read a saved summary by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary_id": {"type": "string"}
                },
                "required": ["summary_id"],
            },
        ),
        Tool(
            name="storage.list_summaries",
            description="List saved summaries with optional filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filter by category"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags (all must match)",
                    },
                    "from_iso": {"type": "string", "description": "Filter from this timestamp"},
                    "to_iso": {"type": "string", "description": "Filter to this timestamp"},
                    "last_n": {
                        "type": "integer",
                        "description": "Return only the N most recent summaries",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="storage.save_report",
            description="Save a Markdown report to the reports directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Markdown report content"},
                    "title": {"type": "string", "description": "Report title"},
                    "task_id": {"type": "string", "description": "Task ID that generated this report"},
                },
                "required": ["content", "title", "task_id"],
            },
        ),
        Tool(
            name="storage.read_report",
            description="Read a Markdown report by its file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "report_path": {
                        "type": "string",
                        "description": "Absolute path to the report file",
                    }
                },
                "required": ["report_path"],
            },
        ),
    ]


# ── Tool dispatcher ───────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "storage.save_summary":
            result = _save_summary(
                arguments["content"],
                arguments["category"],
                arguments.get("tags"),
            )
        elif name == "storage.read_summary":
            result = _read_summary(arguments["summary_id"])
        elif name == "storage.list_summaries":
            result = _list_summaries(
                category=arguments.get("category"),
                tags=arguments.get("tags"),
                from_iso=arguments.get("from_iso"),
                to_iso=arguments.get("to_iso"),
                last_n=arguments.get("last_n"),
            )
        elif name == "storage.save_report":
            result = _save_report(
                arguments["content"],
                arguments["title"],
                arguments["task_id"],
            )
        elif name == "storage.read_report":
            result = _read_report(arguments["report_path"])
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except (ToolError, PathTraversalError) as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    except Exception as exc:
        logger.exception("storage tool error in %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ── Implementation ────────────────────────────────────────────────────────────

def _summaries_dir() -> Path:
    from core.config import app_config
    d = Path(app_config.storage.base_dir).expanduser() / "summaries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reports_dir() -> Path:
    from core.config import app_config
    d = Path(app_config.storage.base_dir).expanduser() / "data" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_summary(
    content: str,
    category: str,
    tags: list[str] | None = None,
) -> dict:
    summary_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    record = {
        "id": summary_id,
        "category": category,
        "tags": tags or [],
        "created_at": now,
        "content": content,
    }
    path = _summaries_dir() / f"{summary_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"summary_id": summary_id, "path": str(path)}


def _read_summary(summary_id: str) -> dict:
    path = _summaries_dir() / f"{summary_id}.json"
    if not path.exists():
        raise ToolError(
            f"Summary '{summary_id}' not found",
            tool_name="storage.read_summary",
        )
    record = json.loads(path.read_text(encoding="utf-8"))
    return {
        "content": record["content"],
        "metadata": {
            "id": record["id"],
            "category": record["category"],
            "tags": record["tags"],
            "created_at": record["created_at"],
        },
    }


def _list_summaries(
    category: str | None = None,
    tags: list[str] | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
    last_n: int | None = None,
) -> list[dict]:
    summaries_dir = _summaries_dir()
    results = []

    from_dt = datetime.fromisoformat(from_iso) if from_iso else None
    to_dt = datetime.fromisoformat(to_iso) if to_iso else None

    for json_file in summaries_dir.glob("*.json"):
        try:
            record = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # Filter by category
        if category and record.get("category") != category:
            continue

        # Filter by tags (all must match)
        if tags:
            record_tags = set(record.get("tags", []))
            if not all(t in record_tags for t in tags):
                continue

        # Filter by time range
        created_at_str = record.get("created_at", "")
        if from_dt or to_dt:
            try:
                created_dt = datetime.fromisoformat(created_at_str)
                if created_dt.tzinfo is None:
                    from datetime import timezone as tz
                    created_dt = created_dt.replace(tzinfo=tz.utc)
                if from_dt and created_dt < from_dt:
                    continue
                if to_dt and created_dt > to_dt:
                    continue
            except ValueError:
                continue

        results.append({
            "summary_id": record["id"],
            "category": record.get("category", ""),
            "tags": record.get("tags", []),
            "created_at": created_at_str,
            "snippet": record.get("content", "")[:200],
        })

    # Sort by created_at descending
    results.sort(key=lambda x: x["created_at"], reverse=True)

    if last_n is not None:
        results = results[:last_n]

    return results


def _slugify(text: str) -> str:
    """Convert a title to a safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:50]


def _save_report(content: str, title: str, task_id: str) -> dict:
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    filename = f"{date_str}_{task_id}_{_slugify(title)}.md"
    report_path = _reports_dir() / filename
    report_path.write_text(content, encoding="utf-8")
    return {"report_path": str(report_path)}


def _read_report(report_path: str) -> dict:
    reports_dir = _reports_dir().resolve()
    requested = Path(report_path).resolve()

    # Path traversal protection
    try:
        requested.relative_to(reports_dir)
    except ValueError:
        raise PathTraversalError(
            f"Access denied: '{report_path}' is outside the reports directory",
            tool_name="storage.read_report",
        )

    if not requested.exists():
        raise ToolError(
            f"Report not found: '{report_path}'",
            tool_name="storage.read_report",
        )

    return {"content": requested.read_text(encoding="utf-8")}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from tools.shared.mcp_base import run_server
    asyncio.run(run_server(app))
