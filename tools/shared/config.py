"""
tools.shared.config — Tool configuration helpers.

Extracts tool-relevant configuration from the global AppConfig,
providing a single access point for all MCP Tool Packages.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolConfig:
    """Flattened configuration relevant to MCP Tool Packages."""
    # LLM
    default_model: str
    vision_model: str
    fallback_model: str
    openai_api_key: str | None
    anthropic_api_key: str | None
    gemini_api_key: str | None

    # Notification
    feishu_default_webhook: str | None

    # Knowledge
    search_provider: str
    tavily_api_key: str | None

    # Storage
    base_dir: str

    # Vision variant
    yolo_variant: str


def get_tool_config() -> ToolConfig:
    """
    Extract tool-relevant configuration from the global AppConfig and EnvProfile.

    Returns:
        ToolConfig with all fields populated.
    """
    from core.config import app_config
    from env.state import get_env_profile

    profile = get_env_profile()

    return ToolConfig(
        default_model=app_config.llm.default_model,
        vision_model=app_config.llm.vision_model,
        fallback_model=app_config.llm.fallback_model,
        openai_api_key=app_config.llm.api_keys.openai,
        anthropic_api_key=app_config.llm.api_keys.anthropic,
        gemini_api_key=app_config.llm.api_keys.gemini,
        feishu_default_webhook=app_config.notify.feishu_default_webhook,
        search_provider=app_config.knowledge.search_provider,
        tavily_api_key=app_config.knowledge.tavily_api_key,
        base_dir=app_config.storage.base_dir,
        yolo_variant=profile.yolo_variant,
    )
