"""
core.bus — global bus singleton, poll_manager singleton, and re-exports.

Usage:
    from core.bus import bus, poll_manager
    await bus.put(msg)
    poll_manager.start()
"""
from core.bus.bus import DeviceDataBus
from core.config import app_config, devices_config
from env.state import get_env_profile

# Global bus singleton
bus = DeviceDataBus(
    ring_buffer_size=app_config.bus.ring_buffer_size,
    base_dir=app_config.storage.base_dir,
)

# Global poll manager singleton (lazy — call poll_manager.start() to activate)
from core.bus.poll_manager import PollManager

poll_manager = PollManager(
    devices_config=devices_config,
    bus=bus,
    env_profile=get_env_profile(),
)

__all__ = ["bus", "poll_manager", "DeviceDataBus", "PollManager"]
