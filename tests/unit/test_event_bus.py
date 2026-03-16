"""
Unit tests for EventBus (T24 — Sprint 2 gate).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.scheduler.event_bus import EventBus


class TestEventBusSubscribePublish:
    @pytest.mark.asyncio
    async def test_sync_callback_triggered(self):
        """publish triggers a sync callback."""
        bus = EventBus()
        received = []

        def callback(event, data):
            received.append((event, data))

        bus.subscribe("task.completed", callback)
        await bus.publish("task.completed", {"task_id": "plant_monitor"})

        assert len(received) == 1
        assert received[0][0] == "task.completed"
        assert received[0][1]["task_id"] == "plant_monitor"

    @pytest.mark.asyncio
    async def test_async_callback_triggered(self):
        """publish triggers an async callback."""
        bus = EventBus()
        received = []

        async def async_callback(event, data):
            received.append((event, data))

        bus.subscribe("task.completed", async_callback)
        await bus.publish("task.completed", {"result": "ok"})

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_triggered(self):
        """All subscribers for an event are triggered."""
        bus = EventBus()
        counts = [0, 0]

        def cb1(event, data):
            counts[0] += 1

        def cb2(event, data):
            counts[1] += 1

        bus.subscribe("sensor.alert", cb1)
        bus.subscribe("sensor.alert", cb2)
        await bus.publish("sensor.alert", {})

        assert counts == [1, 1]

    @pytest.mark.asyncio
    async def test_no_subscribers_no_error(self):
        """publish with no subscribers does not raise."""
        bus = EventBus()
        await bus.publish("nonexistent.event", {"data": "test"})  # Should not raise

    @pytest.mark.asyncio
    async def test_publish_without_data(self):
        """publish without data passes empty dict to callback."""
        bus = EventBus()
        received_data = []

        def callback(event, data):
            received_data.append(data)

        bus.subscribe("test.event", callback)
        await bus.publish("test.event")

        assert received_data == [{}]


class TestEventBusWildcard:
    @pytest.mark.asyncio
    async def test_wildcard_matches_all_device_push(self):
        """Wildcard pattern 'device.push:*' matches all device push events."""
        bus = EventBus()
        received = []

        def callback(event, data):
            received.append(event)

        bus.subscribe("device.push:*", callback)
        await bus.publish("device.push:lab_temp_sensor", {"value": 25.3})
        await bus.publish("device.push:plant_soil_sensor", {"value": 42.0})

        assert "device.push:lab_temp_sensor" in received
        assert "device.push:plant_soil_sensor" in received
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_wildcard_does_not_match_unrelated(self):
        """Wildcard 'device.push:*' does not match 'task.completed'."""
        bus = EventBus()
        received = []

        def callback(event, data):
            received.append(event)

        bus.subscribe("device.push:*", callback)
        await bus.publish("task.completed", {})

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_exact_and_wildcard_both_match(self):
        """Both exact and wildcard subscribers are triggered for matching events."""
        bus = EventBus()
        exact_count = [0]
        wildcard_count = [0]

        def exact_cb(event, data):
            exact_count[0] += 1

        def wildcard_cb(event, data):
            wildcard_count[0] += 1

        bus.subscribe("device.push:lab_temp_sensor", exact_cb)
        bus.subscribe("device.push:*", wildcard_cb)
        await bus.publish("device.push:lab_temp_sensor", {})

        assert exact_count[0] == 1
        assert wildcard_count[0] == 1


class TestEventBusUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_callback(self):
        """unsubscribe prevents callback from being triggered."""
        bus = EventBus()
        received = []

        def callback(event, data):
            received.append(event)

        bus.subscribe("test.event", callback)
        bus.unsubscribe("test.event", callback)
        await bus.publish("test.event", {})

        assert len(received) == 0

    def test_clear_removes_all_subscriptions(self):
        """clear() removes all subscriptions."""
        bus = EventBus()
        bus.subscribe("event.a", lambda e, d: None)
        bus.subscribe("event.b", lambda e, d: None)
        bus.clear()
        assert len(bus._subscribers) == 0
