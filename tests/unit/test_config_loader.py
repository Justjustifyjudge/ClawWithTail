"""
Unit tests for configuration loader (T09 — Sprint 0 gate).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.config.loader import load_app_config, load_devices_config


class TestLoadAppConfig:
    def test_loads_default_config(self):
        """Default config.yaml loads without error and has correct defaults."""
        config = load_app_config()
        assert config.bus.webhook_port == 17171
        assert config.bus.ring_buffer_size == 1000
        assert config.storage.base_dir == "~/.clawtail"
        assert config.knowledge.search_provider == "tavily"

    def test_env_var_substitution(self, tmp_path: Path, monkeypatch):
        """${ENV_VAR} placeholders are replaced with environment variable values."""
        monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test-12345")
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "llm:\n  api_keys:\n    openai: \"${TEST_OPENAI_KEY}\"\n",
            encoding="utf-8",
        )
        config = load_app_config(config_yaml)
        assert config.llm.api_keys.openai == "sk-test-12345"

    def test_env_var_not_set_keeps_placeholder(self, tmp_path: Path, monkeypatch):
        """Unset ${ENV_VAR} placeholders are kept as-is (not replaced with None)."""
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "notify:\n  feishu_default_webhook: \"${NONEXISTENT_VAR}\"\n",
            encoding="utf-8",
        )
        config = load_app_config(config_yaml)
        assert config.notify.feishu_default_webhook == "${NONEXISTENT_VAR}"

    def test_missing_file_returns_defaults(self, tmp_path: Path):
        """Missing config file returns AppConfig with all defaults."""
        config = load_app_config(tmp_path / "nonexistent.yaml")
        assert config.bus.webhook_port == 17171


class TestLoadDevicesConfig:
    def test_loads_default_devices(self):
        """Default devices.yaml loads and contains exactly 3 devices."""
        devices = load_devices_config()
        assert len(devices.devices) == 3

    def test_device_ids(self):
        """Default devices have the expected IDs."""
        devices = load_devices_config()
        ids = {d.id for d in devices.devices}
        assert "desk_camera" in ids
        assert "plant_soil_sensor" in ids
        assert "lab_temp_sensor" in ids

    def test_missing_file_returns_empty(self, tmp_path: Path):
        """Missing devices file returns empty DevicesConfig."""
        devices = load_devices_config(tmp_path / "nonexistent.yaml")
        assert devices.devices == []
