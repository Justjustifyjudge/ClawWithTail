"""
tools.notify.server — notify MCP Tool Package.

Provides tools for sending notifications via Feishu (Lark) webhook.

Tools:
  notify.feishu_send         — send a plain text message to Feishu
  notify.feishu_send_report  — send a formatted report summary to Feishu
"""
from __future__ import annotations

import asyncio
import json
import logging

from mcp.server import Server
from mcp.types import TextContent, Tool

import httpx
from tools.shared.config import get_tool_config
from tools.shared.errors import ExternalAPIError

logger = logging.getLogger(__name__)

app = Server("notify-tools")


# ── Tool definitions ──────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="notify.feishu_send",
            description="Send a plain text message to a Feishu (Lark) webhook.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The text message to send",
                    },
                    "webhook_url": {
                        "type": "string",
                        "description": (
                            "Optional Feishu webhook URL. "
                            "Uses the default from config if omitted."
                        ),
                    },
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="notify.feishu_send_report",
            description="Send a formatted report summary to Feishu with title, summary, and report path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Report title"},
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of the report (1-3 sentences)",
                    },
                    "report_path": {
                        "type": "string",
                        "description": "Local file path where the full report is saved",
                    },
                },
                "required": ["title", "summary", "report_path"],
            },
        ),
    ]


# ── Tool dispatcher ───────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "notify.feishu_send":
            result = await _feishu_send(
                arguments["message"],
                arguments.get("webhook_url"),
            )
        elif name == "notify.feishu_send_report":
            result = await _feishu_send_report(
                arguments["title"],
                arguments["summary"],
                arguments["report_path"],
            )
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as exc:
        logger.exception("notify tool error in %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ── Implementation ────────────────────────────────────────────────────────────

async def _feishu_send(message: str, webhook_url: str | None = None) -> dict:
    cfg = get_tool_config()
    url = webhook_url or cfg.feishu_default_webhook
    if not url:
        raise ExternalAPIError(
            "No Feishu webhook URL configured. "
            "Set FEISHU_WEBHOOK_URL in .env or pass webhook_url explicitly.",
            tool_name="notify.feishu_send",
        )

    payload = {
        "msg_type": "text",
        "content": {"text": message},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
        logger.info(
            "notify.feishu_send: status=%d message_len=%d",
            response.status_code, len(message),
        )
        return {
            "success": response.status_code == 200,
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        logger.warning("notify.feishu_send: HTTP error: %s", exc)
        return {"success": False, "status_code": 0, "error": str(exc)}


async def _feishu_send_report(
    title: str,
    summary: str,
    report_path: str,
) -> dict:
    message = (
        f"📋 **{title}**\n\n"
        f"{summary}\n\n"
        f"📁 Report saved: `{report_path}`"
    )
    result = await _feishu_send(message)
    return {"success": result.get("success", False)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from tools.shared.mcp_base import run_server
    asyncio.run(run_server(app))
