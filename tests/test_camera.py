"""Regression tests for the MQTT camera entity."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = REPO_ROOT / "custom_components" / "frigate_identity"


def _install_homeassistant_stubs() -> dict[str, Any]:
    """Install minimal Home Assistant stubs for the camera module."""
    existing = sys.modules.get("homeassistant.components.mqtt")
    if existing is not None and hasattr(existing, "_subscription_store"):
        return existing._subscription_store

    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    mqtt = types.ModuleType("homeassistant.components.mqtt")
    camera_module = types.ModuleType("homeassistant.components.camera")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")

    subscription_store: dict[str, Any] = {}

    async def async_subscribe(hass, topic, callback, encoding=None):
        subscription_store["hass"] = hass
        subscription_store["topic"] = topic
        subscription_store["callback"] = callback
        subscription_store["encoding"] = encoding

        def _unsubscribe() -> None:
            subscription_store["unsubscribed"] = True

        return _unsubscribe

    class Camera:
        """Minimal camera base class for regression testing."""

        def __init__(self) -> None:
            self._token_updates = 0
            self._write_count = 0
            self.hass = None

        def async_update_token(self) -> None:
            self._token_updates += 1

        def async_write_ha_state(self) -> None:
            self._write_count += 1

    class ConfigEntry:
        """Placeholder type."""

    class HomeAssistant:
        """Placeholder type."""

    def callback(func: Any) -> Any:
        return func

    mqtt.async_subscribe = async_subscribe
    mqtt._subscription_store = subscription_store
    camera_module.Camera = Camera
    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = callback
    entity_platform.AddEntitiesCallback = object

    homeassistant.components = components

    sys.modules["homeassistant.components.mqtt"] = mqtt
    sys.modules["homeassistant.components.camera"] = camera_module
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    return subscription_store


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


def _load_camera_module():
    """Load the constants, registry, and camera modules into a fake package."""
    subscription_store = _install_homeassistant_stubs()

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
    _load_module("custom_components.frigate_identity.person_registry", "person_registry.py")
    camera_module = _load_module(
        "custom_components.frigate_identity.camera",
        "camera.py",
    )
    return camera_module, subscription_store


CAMERA_MODULE, SUBSCRIPTIONS = _load_camera_module()
FrigateIdentityCamera = CAMERA_MODULE.FrigateIdentityCamera


class CameraTests(unittest.IsolatedAsyncioTestCase):
    """Regression coverage for MQTT snapshot handling."""

    async def test_incoming_snapshot_refreshes_camera_token(self) -> None:
        """A new MQTT snapshot should invalidate the frontend image cache."""
        entity = FrigateIdentityCamera("Alice", "identity")
        entity.hass = object()

        await entity.async_added_to_hass()

        self.assertEqual(SUBSCRIPTIONS["topic"], "identity/snapshots/Alice")
        self.assertIsNone(entity._image)

        msg = types.SimpleNamespace(payload=b"jpeg-bytes")
        SUBSCRIPTIONS["callback"](msg)

        self.assertEqual(entity._image, b"jpeg-bytes")
        self.assertEqual(entity._token_updates, 1)
        self.assertEqual(entity._write_count, 1)


if __name__ == "__main__":
    unittest.main()