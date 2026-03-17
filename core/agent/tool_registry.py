"""
core.agent.tool_registry — Routes LLM tool calls to the correct MCP server.

The ToolRegistry manages a pool of MCP server subprocess connections.
When the LLM emits a tool call, the registry:
  1. Looks up which MCP server owns that tool
  2. Sends a JSON-RPC `tools/call` request to that server
  3. Returns the result string back to the ReAct loop

Design: MCP servers run as subprocesses communicating over stdio.
The registry uses mcp.client.stdio to manage these connections.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def _run_stdio_session(
    params,
    ready_event: asyncio.Event,
    result_holder: dict,
    stop_event: asyncio.Event,
) -> None:
    """
    Background task that owns the full lifetime of a stdio_client context.

    anyio's CancelScope inside stdio_client MUST be entered and exited in the
    same asyncio Task.  Calling __aenter__ / __aexit__ manually from different
    tasks violates this invariant and raises:
        RuntimeError: Attempted to exit cancel scope in a different task

    Solution: keep the entire `async with stdio_client(...)` block alive inside
    a dedicated background Task.  We signal the caller via asyncio.Event once
    the session is ready, then wait on stop_event before tearing down.
    """
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    try:
        async with stdio_client(params) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            async with session:
                await session.initialize()
                tools_response = await session.list_tools()
                result_holder["session"] = session
                result_holder["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description or "",
                            "parameters": t.inputSchema,
                        },
                    }
                    for t in tools_response.tools
                ]
                ready_event.set()          # unblock register_server
                await stop_event.wait()    # keep context alive until stop()
    except Exception as exc:
        result_holder["error"] = exc
        ready_event.set()  # unblock caller so it can raise


class ToolRegistry:
    """
    Registry that maps tool names to MCP server processes and dispatches calls.

    Usage:
        registry = ToolRegistry()
        await registry.start()
        result = await registry.dispatch("vision.capture_frame", {"source_id": "desk_camera"})
        tools = await registry.get_all_tools()
        await registry.stop()
    """

    def __init__(self) -> None:
        # Maps server_name → {"session": ClientSession, "tools": list[dict],
        #                      "task": asyncio.Task, "stop_event": asyncio.Event}
        self._servers: dict[str, dict] = {}
        # Maps tool_name → server_name (populated after start())
        self._tool_map: dict[str, str] = {}

    async def register_server(
        self,
        server_name: str,
        command: list[str],
    ) -> None:
        """
        Start an MCP server subprocess and register all its tools.

        Args:
            server_name: Logical name (e.g. "vision", "sensor")
            command: Command to launch the server (e.g. ["python", "-m", "tools.vision.server"])
        """
        from mcp import StdioServerParameters

        params = StdioServerParameters(command=command[0], args=command[1:])

        ready_event = asyncio.Event()
        stop_event = asyncio.Event()
        result_holder: dict = {}

        # Launch a dedicated background task that owns the stdio_client lifetime.
        # This avoids the anyio CancelScope cross-task violation.
        task = asyncio.create_task(
            _run_stdio_session(params, ready_event, result_holder, stop_event),
            name=f"mcp-{server_name}",
        )

        # Wait for the session to be ready (or fail)
        await ready_event.wait()

        if "error" in result_holder:
            task.cancel()
            raise RuntimeError(
                f"MCP server '{server_name}' failed to start: {result_holder['error']}"
            ) from result_holder["error"]

        session = result_holder["session"]
        tools = result_holder["tools"]

        self._servers[server_name] = {
            "session": session,
            "tools": tools,
            "command": command,
            "task": task,
            "stop_event": stop_event,
        }

        # Build reverse map: tool_name → server_name
        for tool in tools:
            self._tool_map[tool["function"]["name"]] = server_name

        logger.info(
            "ToolRegistry: registered server '%s' with %d tools: %s",
            server_name,
            len(tools),
            [t["function"]["name"] for t in tools],
        )

    async def get_all_tools(self) -> list[dict]:
        """
        Return all registered tools as a flat list of JSON Schema dicts.
        Used to populate the LLM's `tools` parameter.
        """
        all_tools = []
        for server_info in self._servers.values():
            all_tools.extend(server_info["tools"])
        return all_tools

    async def dispatch(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Route a tool call to the correct MCP server and return the result.

        Args:
            tool_name: Full tool name (e.g. "vision.capture_frame")
            args: Tool arguments dict

        Returns:
            Result as a string (JSON-serialized if the result is structured)

        Raises:
            KeyError: if tool_name is not registered
            RuntimeError: if the MCP call fails
        """
        import json

        server_name = self._tool_map.get(tool_name)
        if server_name is None:
            raise KeyError(
                f"ToolRegistry: unknown tool '{tool_name}'. "
                f"Registered tools: {list(self._tool_map.keys())}"
            )

        session = self._servers[server_name]["session"]
        try:
            result = await session.call_tool(tool_name, args)
        except Exception as exc:
            raise RuntimeError(
                f"ToolRegistry: MCP call to '{tool_name}' failed: {exc}"
            ) from exc

        # Extract text content from MCP result
        if result.content:
            parts = []
            for content_item in result.content:
                if hasattr(content_item, "text"):
                    parts.append(content_item.text)
                else:
                    parts.append(str(content_item))
            return "\n".join(parts)
        return ""

    async def stop(self) -> None:
        """Gracefully shut down all MCP server connections."""
        for server_name, server_info in self._servers.items():
            try:
                # Signal the background task to exit the stdio_client context
                server_info["stop_event"].set()
                # Give it a moment to clean up gracefully
                try:
                    await asyncio.wait_for(server_info["task"], timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    server_info["task"].cancel()
                logger.info("ToolRegistry: stopped server '%s'", server_name)
            except Exception as exc:
                logger.warning(
                    "ToolRegistry: error stopping server '%s': %s", server_name, exc
                )
        self._servers.clear()
        self._tool_map.clear()
