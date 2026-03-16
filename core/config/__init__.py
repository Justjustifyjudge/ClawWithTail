"""
core.config — global configuration singletons.

Usage:
    from core.config import app_config, devices_config
"""
from core.config.loader import load_app_config, load_devices_config
from core.config.models import AppConfig, DevicesConfig

# Lazy-loaded singletons — populated on first import
app_config: AppConfig = load_app_config()
devices_config: DevicesConfig = load_devices_config()

__all__ = ["app_config", "devices_config", "AppConfig", "DevicesConfig"]
