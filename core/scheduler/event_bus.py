"""
core.scheduler.event_bus — Lightweight internal event bus.

Provides a simple pub/sub mechanism for internal ClawWithTail events.
Supports wildcard event names using fnmatch patterns.

Usage:
    from core.scheduler.event_bus import event_bus

    event_bus.subscribe("device.push:*", my_callback)
    await event_bus.publish("device.push:lab_temp_sensor", {"value": 25.3})
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Callback type: sync or async function accepting (event: str, data: dict)
EventCallback = Callable[[str, dict], None | Awaitable[None]]


class EventBus:
    """
    Lightweight asyncio-safe internal event bus.

    Supports:
      - Exact event name matching: "task.completed"
      - Wildcard matching: "device.push:*" matches "device.push:lab_temp_sensor"
    """

    def __init__(self) -> None:
        # Maps pattern → list of callbacks
        self._subscribers: dict[str, list[EventCallback]] = {}

    def subscribe(self, event_pattern: str, callback: EventCallback) -> None:
        """
        Register a callback for an event pattern.

        Args:
            event_pattern: Exact event name or fnmatch pattern (e.g. "device.push:*")
            callback: Sync or async callable(event_name, data)
        """
        if event_pattern not in self._subscribers:
            self._subscribers[event_pattern] = []
        self._subscribers[event_pattern].append(callback)
        logger.debug("EventBus: subscribed to '%s'", event_pattern)

    def unsubscribe(self, event_pattern: str, callback: EventCallback) -> None:
        """Remove a specific callback from an event pattern."""
        if event_pattern in self._subscribers:
            try:
                self._subscribers[event_pattern].remove(callback)
            except ValueError:
                pass

    async def publish(self, event: str, data: dict | None = None) -> None:
        """
        Publish an event to all matching subscribers.

        Matching is done via fnmatch, so wildcards are supported.
        Both sync and async callbacks are supported.

        Args:
            event: The event name to publish (e.g. "device.push:lab_temp_sensor")
            data: Optional event payload dict
        """
        if data is None:
            data = {}

        matched_callbacks: list[EventCallback] = []
        for pattern, callbacks in self._subscribers.items():
            if fnmatch.fnmatch(event, pattern):
                matched_callbacks.extend(callbacks)

        if not matched_callbacks:
            logger.debug("EventBus: no subscribers for '%s'", event)
            return

        logger.debug(
            "EventBus: publishing '%s' to %d subscriber(s)", event, len(matched_callbacks)
        )

        for callback in matched_callbacks:
            try:
                result = callback(event, data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning(
                    "EventBus: callback error for event '%s': %s", event, exc
                )

    def clear(self) -> None:
        """Remove all subscriptions (useful for testing)."""
        self._subscribers.clear()


# Global singleton
event_bus = EventBus()
