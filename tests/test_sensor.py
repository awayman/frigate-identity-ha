"""Regression tests for sensor MQTT metadata handling."""
from __future__ import annotations

import importlib.util
import asyncio
import json
import sys
import types
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = REPO_ROOT / "custom_components" / "frigate_identity"


def _install_homeassistant_stubs() -> dict[str, list[dict[str, Any]]]:
    """Install minimal Home Assistant stubs for sensor module loading."""
    existing = sys.modules.get("homeassistant.components.mqtt")
    if existing is not None and hasattr(existing, "_subscriptions"):
        return {"subscriptions": existing._subscriptions}

    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    mqtt = types.ModuleType("homeassistant.components.mqtt")
    sensor_module = types.ModuleType("homeassistant.components.sensor")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    subscriptions: list[dict[str, Any]] = []

    async def async_subscribe(hass, topic, callback, encoding="utf-8"):
        subscriptions.append(
            {
                "hass": hass,
                "topic": topic,
                "callback": callback,
                "encoding": encoding,
                "unsubscribed": False,
            }
        )

        def _unsubscribe() -> None:
            subscriptions[-1]["unsubscribed"] = True

        return _unsubscribe

    class SensorEntity:
        """Minimal sensor base class for regression testing."""

        def __init__(self) -> None:
            self.hass = None
            self._write_count = 0

        def async_write_ha_state(self) -> None:
            self._write_count = getattr(self, "_write_count", 0) + 1

    class ConfigEntry:
        """Placeholder type."""

    class HomeAssistant:
        """Placeholder type."""

    def callback(func: Any) -> Any:
        return func

    def async_get(_hass: Any) -> Any:
        return types.SimpleNamespace(entities={})

    mqtt.async_subscribe = async_subscribe
    mqtt._subscriptions = subscriptions
    sensor_module.SensorEntity = SensorEntity
    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = callback
    entity_platform.AddEntitiesCallback = object
    entity_registry.async_get = async_get

    homeassistant.components = components

    sys.modules["homeassistant.components.mqtt"] = mqtt
    sys.modules["homeassistant.components.sensor"] = sensor_module
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry

    return {"subscriptions": subscriptions}


def _load_module(module_name: str, file_name: str):
    """Load a module from the custom component without importing Home Assistant."""
    spec = importlib.util.spec_from_file_location(module_name, MODULE_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_sensor_module():
    """Load constants, registry, and sensor modules into a fake package."""
    stores = _install_homeassistant_stubs()

    custom_components = sys.modules.setdefault(
        "custom_components",
        types.ModuleType("custom_components"),
    )
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]

    integration_package = sys.modules.setdefault(
        "custom_components.frigate_identity",
        types.ModuleType("custom_components.frigate_identity"),
    )
    integration_package.__path__ = [str(MODULE_DIR)]

    _load_module("custom_components.frigate_identity.const", "const.py")
    registry_module = _load_module("custom_components.frigate_identity.person_registry", "person_registry.py")
    sensor_module = _load_module("custom_components.frigate_identity.sensor", "sensor.py")
    return sensor_module, registry_module, stores


SENSOR_MODULE, REGISTRY_MODULE, SUBSCRIPTION_STORE = _load_sensor_module()
FrigateIdentityLastPersonSensor = SENSOR_MODULE.FrigateIdentityLastPersonSensor
PersonRegistry = REGISTRY_MODULE.PersonRegistry


class _FakeBus:
    def async_fire(self, _event_name: str, _event_data: dict[str, Any]) -> None:
        return


class _FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.bus = _FakeBus()
        self._tasks: list[asyncio.Task[Any]] = []

    def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task

    async def drain_tasks(self) -> None:
        tasks = [task for task in self._tasks if not task.done()]
        self._tasks.clear()
        if tasks:
            await asyncio.gather(*tasks)


class SensorMetadataTests(unittest.IsolatedAsyncioTestCase):
    """Regression tests for snapshot metadata updates."""

    async def test_snapshot_metadata_updates_registry(self) -> None:
        """Snapshot metadata messages should update the same person registry path."""
        hass = _FakeHass()
        registry = PersonRegistry(hass)
        entity = FrigateIdentityLastPersonSensor("identity", registry)
        entity.hass = hass

        await entity.async_added_to_hass()

        by_topic = {
            sub["topic"]: sub["callback"]
            for sub in SUBSCRIPTION_STORE["subscriptions"]
        }
        self.assertIn("identity/person/#", by_topic)
        self.assertIn("identity/snapshots/#", by_topic)

        metadata_payload = {
            "person_id": "Alice",
            "camera": "front_door",
            "timestamp": 12345,
            "source": "mqtt_snapshot",
            "zones": ["porch"],
        }
        msg = types.SimpleNamespace(
            topic="identity/snapshots/Alice/metadata",
            payload=json.dumps(metadata_payload),
        )

        by_topic["identity/snapshots/#"](msg)
        await hass.drain_tasks()

        alice = registry.get_person("Alice")
        self.assertIsNotNone(alice)
        assert alice is not None
        self.assertEqual(alice.camera, "front_door")
        self.assertEqual(alice.frigate_zones, ["porch"])
        self.assertEqual(entity._attr_native_value, "Alice")
        self.assertEqual(entity._attr_extra_state_attributes["frigate_zones"], ["porch"])


if __name__ == "__main__":
    unittest.main()
