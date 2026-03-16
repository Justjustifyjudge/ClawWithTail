"""
tools.shared.mcp_base — Common MCP Server startup pattern.

All ClawWithTail MCP Tool Packages use this module to create and run
their MCP servers in a consistent way.
"""
from __future__ import annotations

import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)


def create_mcp_server(name: str) -> Server:
    """
    Create a new MCP Server instance with the given name.

    Args:
        name: Human-readable server name (e.g. "vision-tools", "sensor-tools")

    Returns:
        A configured mcp.server.Server instance ready for tool registration.
    """
    return Server(name)


async def run_server(app: Server) -> None:
    """
    Run an MCP Server over stdio (standard MCP transport).

    This is the main entry point for all ClawWithTail MCP servers.
    Call this from the `if __name__ == "__main__"` block of each server.py.

    Args:
        app: The configured MCP Server instance with all tools registered.
    """
    logger.info("Starting MCP server: %s", app.name)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )
