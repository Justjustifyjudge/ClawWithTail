"""
core.config — global configuration singletons.

Usage:
    from core.config import app_config, devices_config
"""
from pathlib import Path

from dotenv import load_dotenv

from core.config.loader import load_app_config, load_devices_config
from core.config.models import AppConfig, DevicesConfig

# Load .env before reading config so ${ENV_VAR} substitution works correctly
_env_file = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_env_file, override=False)

# Lazy-loaded singletons — populated on first import
app_config: AppConfig = load_app_config()
devices_config: DevicesConfig = load_devices_config()

__all__ = ["app_config", "devices_config", "AppConfig", "DevicesConfig"]
