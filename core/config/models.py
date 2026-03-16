"""
Pydantic v2 configuration models for ClawWithTail.
All models correspond to sections in config/config.yaml and config/devices.yaml.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── LLM ───────────────────────────────────────────────────────────────────────

class LLMApiKeysConfig(BaseModel):
    openai: str | None = None
    anthropic: str | None = None
    gemini: str | None = None


class LLMConfig(BaseModel):
    default_model: str = "gpt-4o"
    vision_model: str = "gpt-4o"
    fallback_model: str = "gpt-4o-mini"
    api_keys: LLMApiKeysConfig = Field(default_factory=LLMApiKeysConfig)
    # Optional: override the API base URL for OpenAI-compatible endpoints
    # (e.g. DeepSeek, Moonshot, local Ollama). None = use provider default.
    base_url: str | None = None


# ── Notification ──────────────────────────────────────────────────────────────

class NotifyConfig(BaseModel):
    feishu_default_webhook: str | None = None


# ── Knowledge ─────────────────────────────────────────────────────────────────

class KnowledgeConfig(BaseModel):
    search_provider: Literal["tavily", "serpapi", "searxng"] = "tavily"
    tavily_api_key: str | None = None


# ── Device Data Bus ───────────────────────────────────────────────────────────

class BusConfig(BaseModel):
    webhook_port: int = 17171
    ring_buffer_size: int = 1000


# ── Storage ───────────────────────────────────────────────────────────────────

class StorageConfig(BaseModel):
    base_dir: str = "~/.clawtail"


# ── Tool Variant Overrides ────────────────────────────────────────────────────

class VisionVariantOverride(BaseModel):
    yolo: str | None = None  # None = auto-detect


class ToolVariantOverridesConfig(BaseModel):
    vision: VisionVariantOverride = Field(default_factory=VisionVariantOverride)


# ── Root AppConfig ────────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    bus: BusConfig = Field(default_factory=BusConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    tool_variant_overrides: ToolVariantOverridesConfig = Field(
        default_factory=ToolVariantOverridesConfig
    )


# ── Device Config (devices.yaml) ──────────────────────────────────────────────

class DeviceConfig(BaseModel):
    id: str
    type: Literal["camera", "sensor"]
    transport: Literal["usb", "wifi_poll", "wifi_push", "bluetooth", "serial"]
    # Camera-specific
    source: str | None = None          # device index or /dev/videoX
    # WiFi poll-specific
    poll_url: str | None = None
    poll_interval_seconds: int | None = None
    # WiFi push-specific
    push_webhook_path: str | None = None
    # Sensor subtype
    subtype: str | None = None         # e.g. "soil_moisture", "temperature"


class DevicesConfig(BaseModel):
    devices: list[DeviceConfig] = Field(default_factory=list)
