"""Regression tests for Meshtastic geofence integration helpers."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import AsyncMock

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = REPO_ROOT / "custom_components" / "frigate_identity"


def _install_stubs() -> None:
    """Install minimal Home Assistant and voluptuous stubs."""

    class _VolModule(types.ModuleType):
        ALLOW_EXTRA = object()

        @staticmethod
        def Schema(*_args, **_kwargs):
            return lambda value: value

        @staticmethod
        def Required(name):
            return name

        @staticmethod
        def Optional(name, default=None):
            return name

        @staticmethod
        def All(*_args):
            return list

        @staticmethod
        def Length(*_args, **_kwargs):
            return list

        @staticmethod
        def Boolean():
            return bool

        @staticmethod
        def Coerce(value_type):
            return value_type

    sys.modules["voluptuous"] = _VolModule("voluptuous")

    ha_root = types.ModuleType("homeassistant")
    ha_components = types.ModuleType("homeassistant.components")
    ha_sensor = types.ModuleType("homeassistant.components.sensor")
    ha_const = types.ModuleType("homeassistant.const")
    ha_core = types.ModuleType("homeassistant.core")
    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_cv = types.ModuleType("homeassistant.helpers.config_validation")
    ha_entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    ha_storage = types.ModuleType("homeassistant.helpers.storage")
    ha_exceptions = types.ModuleType("homeassistant.exceptions")

    class SensorEntity:
        def __init__(self) -> None:
            self._write_count = 0

        def async_write_ha_state(self) -> None:
            self._write_count = getattr(self, "_write_count", 0) + 1

    class SensorDeviceClass:
        BATTERY = "battery"
        TIMESTAMP = "timestamp"

    class Event:
        def __init__(self, data: dict[str, Any]) -> None:
            self.data = data

    class HomeAssistantError(Exception):
        pass

    class Store:
        _saved: ClassVar[dict[str, Any]] = {}

        def __init__(self, _hass: Any, _version: int, key: str) -> None:
            self._key = key

        async def async_load(self) -> Any:
            return self._saved.get(self._key)

        async def async_save(self, value: Any) -> None:
            self._saved[self._key] = value

    def callback(func: Any) -> Any:
        return func

    ha_sensor.SensorEntity = SensorEntity
    ha_sensor.SensorDeviceClass = SensorDeviceClass
    ha_const.PERCENTAGE = "%"
    ha_core.Event = Event
    ha_core.HomeAssistant = object
    ha_core.ServiceCall = object
    ha_core.callback = callback
    ha_cv.string = str
    ha_cv.entity_id = str
    ha_entity_platform.AddEntitiesCallback = object
    ha_storage.Store = Store
    ha_exceptions.HomeAssistantError = HomeAssistantError

    ha_root.components = ha_components
    ha_root.helpers = ha_helpers
    ha_components.sensor = ha_sensor
    ha_helpers.config_validation = ha_cv
    ha_helpers.entity_platform = ha_entity_platform
    ha_helpers.storage = ha_storage

    stubs = {
        "homeassistant": ha_root,
        "homeassistant.components": ha_components,
        "homeassistant.components.sensor": ha_sensor,
        "homeassistant.const": ha_const,
        "homeassistant.core": ha_core,
        "homeassistant.helpers": ha_helpers,
        "homeassistant.helpers.config_validation": ha_cv,
        "homeassistant.helpers.entity_platform": ha_entity_platform,
        "homeassistant.helpers.storage": ha_storage,
        "homeassistant.exceptions": ha_exceptions,
    }
    for name, module in stubs.items():
        sys.modules[name] = module


def _load_module():
    """Load the geofence module inside a fake package namespace."""
    _install_stubs()

    for key in list(sys.modules):
        if key.startswith("custom_components.frigate_identity"):
            del sys.modules[key]

    custom_components = sys.modules.setdefault(
        "custom_components",
        types.ModuleType("custom_components"),
    )
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]

    integration_package = types.ModuleType("custom_components.frigate_identity")
    integration_package.__path__ = [str(MODULE_DIR)]
    sys.modules["custom_components.frigate_identity"] = integration_package

    spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.meshtastic_geofence",
        MODULE_DIR / "meshtastic_geofence.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["custom_components.frigate_identity.meshtastic_geofence"] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.listeners: dict[str, Any] = {}

    def async_fire(self, event_name: str, event_data: dict[str, Any]) -> None:
        self.events.append((event_name, event_data))

    def async_listen(self, event_name: str, listener: Any):
        self.listeners[event_name] = listener

        def _unsubscribe() -> None:
            self.listeners.pop(event_name, None)

        return _unsubscribe

    def emit(self, event_name: str, event_data: dict[str, Any]) -> None:
        listener = self.listeners[event_name]
        listener(types.SimpleNamespace(data=event_data))


class _FakeStates:
    def __init__(self, entities: dict[str, Any] | None = None) -> None:
        self._entities = entities or {}

    def get(self, entity_id: str) -> Any:
        return self._entities.get(entity_id)


class _FakeServices:
    def __init__(self) -> None:
        self.async_call = AsyncMock()

    def has_service(self, domain: str, service: str) -> bool:
        return domain == "meshtastic" and service == "send_direct_message"


class _FakeHass:
    def __init__(self, relay_attrs: dict[str, Any] | None = None) -> None:
        entity = None
        if relay_attrs is not None:
            entity = types.SimpleNamespace(attributes=relay_attrs)
        self.bus = _FakeBus()
        self.states = _FakeStates({"switch.toy_relay": entity} if entity else {})
        self.services = _FakeServices()


class MeshtasticGeofenceTests(unittest.IsolatedAsyncioTestCase):
    """Focused regression coverage for the Meshtastic geofence backend."""

    def test_validate_polygon_returns_issue_spec_messages(self) -> None:
        self.assertEqual(
            MODULE._validate_polygon([[1.0, 2.0], [3.0, 4.0]]),
            "Polygon must have at least 3 points",
        )
        self.assertEqual(
            MODULE._validate_polygon([[91.0, 0.0], [0.0, 0.0], [1.0, 1.0]]),
            "Latitude must be -90 to 90, longitude -180 to 180",
        )
        self.assertEqual(
            MODULE._validate_polygon(
                [[0.0, 0.0], [1.0, 1.0], [0.0, 1.0], [1.0, 0.0]]
            ),
            "Polygon is self-intersecting",
        )

    async def test_configure_service_sends_compact_payload_and_persists_config(self) -> None:
        hass = _FakeHass(relay_attrs={"gpio_pin": 10})
        registry = MODULE.TrackerRegistry(hass)
        call = types.SimpleNamespace(
            data={
                "tracker_id": "1234",
                "person_name": "Alice",
                "polygon": [
                    [40.7128, -74.0060],
                    [40.7135, -74.0060],
                    [40.7135, -74.0055],
                    [40.7128, -74.0055],
                ],
                "relay_entity": "switch.toy_relay",
            }
        )

        await MODULE.async_handle_configure_tracker_geofence(hass, call, registry)

        self.assertEqual(hass.services.async_call.await_count, 1)
        args = hass.services.async_call.await_args.args
        self.assertEqual(args[0], "meshtastic")
        self.assertEqual(args[1], "send_direct_message")
        payload = json.loads(args[2]["message"])
        self.assertEqual(payload["tracker_id"], "1234")
        self.assertEqual(payload["person_name"], "Alice")
        self.assertEqual(payload["enable_beeper"], True)
        self.assertEqual(payload["relay_gpio"], 10)
        self.assertNotIn("warn_dist_approaching", payload)
        self.assertLessEqual(
            len(args[2]["message"].encode()),
            MODULE.MAX_DIRECT_MESSAGE_BYTES,
        )
        self.assertEqual(registry.get_person("1234"), "Alice")
        self.assertEqual(registry.get_config("1234")["relay_entity"], "switch.toy_relay")
        self.assertIn(
            "frigate_identity.geofence_config_sent",
            [event_name for event_name, _ in hass.bus.events],
        )

    async def test_configure_service_rejects_oversize_payload(self) -> None:
        hass = _FakeHass()
        registry = MODULE.TrackerRegistry(hass)
        call = types.SimpleNamespace(
            data={
                "tracker_id": "1234",
                "person_name": "Alice",
                "geofence_name": "x" * 180,
                "polygon": [
                    [40.7128, -74.0060],
                    [40.7135, -74.0060],
                    [40.7135, -74.0055],
                    [40.7128, -74.0055],
                ],
            }
        )

        with self.assertRaises(MODULE.HomeAssistantError):
            await MODULE.async_handle_configure_tracker_geofence(hass, call, registry)

        self.assertEqual(hass.services.async_call.await_count, 0)
        self.assertIn(
            "frigate_identity.geofence_config_error",
            [event_name for event_name, _ in hass.bus.events],
        )

    async def test_tracker_status_updates_all_sensors_and_fires_transition_events(self) -> None:
        hass = _FakeHass()
        registry = MODULE.TrackerRegistry(hass)
        await registry.async_register_geofence(
            {
                "tracker_id": "1234",
                "person_name": "Alice",
                "geofence_name": "yard",
                "polygon": [[1.0, 1.0], [1.0, 2.0], [2.0, 2.0]],
                "enable_beeper": True,
                "buzzer_gpio": 0,
                "warn_dist_approaching": 50,
                "warn_dist_near": 20,
                "warn_dist_critical": 5,
            }
        )
        added_entities: list[Any] = []

        cleanup = await MODULE.async_setup_tracker_sensors(
            hass,
            registry,
            lambda entities: added_entities.extend(entities),
        )

        self.assertEqual(len(added_entities), 7)

        hass.bus.emit(
            MODULE.MESHTASTIC_EVENT_MESSAGE,
            {
                "sender": "1234",
                "message": json.dumps(
                    {
                        "device": "Tracker-1234",
                        "status": "in_geofence",
                        "latitude": 40.7128,
                        "longitude": -74.0060,
                        "dist_to_boundary": 12.3,
                        "beep_zone": "NEAR",
                        "relay_enabled": True,
                        "battery_percent": 85,
                        "gps_fix": True,
                        "timestamp": 1234567890,
                    }
                ),
            },
        )

        states = {entity._attr_name: entity._attr_native_value for entity in added_entities}
        self.assertEqual(states["Alice Geofence Status"], "in_geofence")
        self.assertEqual(states["Alice Distance To Boundary"], 12.3)
        self.assertEqual(states["Alice Beep Zone"], "NEAR")
        self.assertEqual(states["Alice Battery Percent"], 85)
        self.assertEqual(states["Alice Last Position"], "40.7128,-74.006")
        self.assertEqual(states["Alice Relay State"], "on")

        hass.bus.emit(
            MODULE.MESHTASTIC_EVENT_MESSAGE,
            {
                "sender": "1234",
                "message": json.dumps(
                    {
                        "device": "Tracker-1234",
                        "status": "outside_geofence",
                        "latitude": 40.7127,
                        "longitude": -74.0061,
                        "dist_to_boundary": -1.1,
                        "beep_zone": "OUTSIDE",
                        "relay_enabled": False,
                        "battery_percent": 5,
                        "gps_fix": False,
                        "timestamp": 1234567990,
                    }
                ),
            },
        )

        fired_events = [event_name for event_name, _ in hass.bus.events]
        self.assertIn("frigate_identity.tracker_entered_geofence", fired_events)
        self.assertIn("frigate_identity.tracker_exited_geofence", fired_events)
        self.assertIn("frigate_identity.tracker_battery_low", fired_events)
        self.assertIn("frigate_identity.tracker_no_gps_fix", fired_events)
        cleanup()


if __name__ == "__main__":
    unittest.main()
