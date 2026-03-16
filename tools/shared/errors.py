"""
tools.shared.errors — Common exception types for MCP Tool Packages.
"""
from __future__ import annotations


class ToolError(Exception):
    """
    Base exception for all ClawWithTail MCP Tool errors.

    Attributes:
        message: Human-readable error description.
        tool_name: The name of the tool that raised the error (e.g. "vision.capture_frame").
    """

    def __init__(self, message: str, tool_name: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.tool_name = tool_name

    def __str__(self) -> str:
        if self.tool_name:
            return f"[{self.tool_name}] {self.message}"
        return self.message


class DeviceNotFoundError(ToolError):
    """Raised when a requested device_id is not registered."""


class NoDataError(ToolError):
    """Raised when a device has no data available in the bus."""


class CacheError(ToolError):
    """Raised when a cache read/write operation fails."""


class ExternalAPIError(ToolError):
    """Raised when an external API call (Tavily, Feishu, etc.) fails."""


class PathTraversalError(ToolError):
    """Raised when a path traversal attack is detected."""
