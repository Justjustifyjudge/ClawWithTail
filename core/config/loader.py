"""
Configuration loader for ClawWithTail.
Supports ${ENV_VAR} substitution in YAML values.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from core.config.models import AppConfig, DevicesConfig

# Default config file locations
_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.yaml"
_DEFAULT_DEVICES_PATH = Path(__file__).parent.parent.parent / "config" / "devices.yaml"

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(value: object) -> object:
    """Recursively replace ${ENV_VAR} placeholders with environment variable values."""
    if isinstance(value, str):
        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))  # keep placeholder if not set
        return _ENV_VAR_PATTERN.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def load_app_config(path: str | Path | None = None) -> AppConfig:
    """
    Load AppConfig from a YAML file.
    Falls back to _DEFAULT_CONFIG_PATH if path is None.
    Environment variables in ${VAR} format are substituted automatically.
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        # Return defaults if config file doesn't exist yet
        return AppConfig()
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    substituted = _substitute_env_vars(raw)
    return AppConfig.model_validate(substituted)


def load_devices_config(path: str | Path | None = None) -> DevicesConfig:
    """
    Load DevicesConfig from a YAML file.
    Falls back to _DEFAULT_DEVICES_PATH if path is None.
    """
    devices_path = Path(path) if path else _DEFAULT_DEVICES_PATH
    if not devices_path.exists():
        return DevicesConfig()
    with open(devices_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    substituted = _substitute_env_vars(raw)
    return DevicesConfig.model_validate(substituted)
