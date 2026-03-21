"""Regression tests for the person registry."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = REPO_ROOT / "custom_components" / "frigate_identity"


def _install_homeassistant_stubs() -> None:
    """Install minimal Home Assistant stubs for module loading."""
    if "homeassistant" in sys.modules:
        return

    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    def callback(func: Any) -> Any:
        return func

    class HomeAssistant:  # noqa: D401
        """Placeholder type used by the integration."""

    def async_get(_hass: Any) -> Any:
        return types.SimpleNamespace(entities={})

    core.callback = callback
    core.HomeAssistant = HomeAssistant
    entity_registry.async_get = async_get

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry


def _load_module(module_name: str, file_name: str):
    """Load a module from the custom component without importing HA."""
    spec = importlib.util.spec_from_file_location(
        module_name,
        MODULE_DIR / file_name,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_registry_modules():
    """Load the constants and registry modules into a fake package."""
    _install_homeassistant_stubs()

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

    const_module = _load_module(
        "custom_components.frigate_identity.const",
        "const.py",
    )
    registry_module = _load_module(
        "custom_components.frigate_identity.person_registry",
        "person_registry.py",
    )
    return const_module, registry_module


CONST, REGISTRY_MODULE = _load_registry_modules()
PersonRegistry = REGISTRY_MODULE.PersonRegistry


class _FakeBus:
    """Capture fired events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event_name: str, event_data: dict[str, Any]) -> None:
        self.events.append((event_name, event_data))


class _FakeHass:
    """Minimal Home Assistant object for registry tests."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.bus = _FakeBus()
        self._tasks: list[asyncio.Task[Any]] = []

    def async_create_task(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task

    async def drain_tasks(self) -> None:
        tasks = [task for task in self._tasks if not task.done()]
        self._tasks.clear()
        if tasks:
            await asyncio.gather(*tasks)


class PersonRegistryTests(unittest.IsolatedAsyncioTestCase):
    """Regression coverage for person updates."""

    async def test_existing_person_updates_notify_listeners(self) -> None:
        """Repeated MQTT updates for the same person must notify listeners."""
        hass = _FakeHass()
        registry = PersonRegistry(hass)
        notifications: list[str | None] = []

        def _listener() -> None:
            person = registry.get_person("Alice")
            notifications.append(person.camera if person else None)

        registry.register_listener(_listener)

        registry.async_update_person(
            "Alice",
            {
                "camera": "front_door",
                "event_id": "event-1",
                "timestamp": 1,
                "frigate_zones": ["porch"],
                "confidence": 0.91,
            },
        )
        await hass.drain_tasks()

        registry.async_update_person(
            "Alice",
            {
                "camera": "driveway",
                "event_id": "event-2",
                "timestamp": 2,
                "frigate_zones": ["driveway"],
                "confidence": 0.93,
            },
        )
        await hass.drain_tasks()

        self.assertEqual(notifications, ["front_door", "driveway"])
        self.assertEqual(registry.get_person("Alice").camera, "driveway")
        self.assertEqual(
            [event_name for event_name, _ in hass.bus.events],
            [CONST.EVENT_PERSONS_UPDATED, CONST.EVENT_PERSONS_UPDATED],
        )
        self.assertEqual(
            hass.data[CONST.DOMAIN][CONST.DATA_PERSONS]["Alice"].camera,
            "driveway",
        )


if __name__ == "__main__":
    unittest.main()