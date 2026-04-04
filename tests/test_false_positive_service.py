"""Unit tests for false-positive service helpers in integration __init__.py."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = REPO_ROOT / "custom_components" / "frigate_identity"


def _stub_dependencies() -> None:
    """Install minimal module stubs required to import integration __init__.py."""

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

    sys.modules["voluptuous"] = _VolModule("voluptuous")

    ha_root = types.ModuleType("homeassistant")
    ha_components = types.ModuleType("homeassistant.components")
    ha_mqtt = types.ModuleType("homeassistant.components.mqtt")
    ha_mqtt.async_publish = AsyncMock()
    ha_mqtt.async_subscribe = AsyncMock()
    ha_components.mqtt = ha_mqtt

    ha_config_entries = types.ModuleType("homeassistant.config_entries")
    ha_config_entries.ConfigEntry = object

    class _Platform:
        SENSOR = "sensor"
        CAMERA = "camera"
        BINARY_SENSOR = "binary_sensor"
        SWITCH = "switch"

    ha_const = types.ModuleType("homeassistant.const")
    ha_const.Platform = _Platform

    def _callback(func):
        return func

    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = object
    ha_core.ServiceCall = object
    ha_core.callback = _callback

    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_cv = types.ModuleType("homeassistant.helpers.config_validation")
    ha_cv.ensure_list = lambda value: value
    ha_event = types.ModuleType("homeassistant.helpers.event")
    ha_event.async_call_later = lambda *_a, **_k: None
    ha_event.async_track_time_change = lambda *_a, **_k: None
    ha_event.async_track_time_interval = lambda *_a, **_k: None

    ha_root.components = ha_components
    ha_root.helpers = ha_helpers

    sys.modules["homeassistant"] = ha_root
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.mqtt"] = ha_mqtt
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.config_validation"] = ha_cv
    sys.modules["homeassistant.helpers.event"] = ha_event

    # Stub sibling modules imported by __init__.py but not exercised in these tests.
    dash_mod = types.ModuleType("custom_components.frigate_identity.dashboard")
    dash_mod.async_generate_dashboard = AsyncMock()
    reg_mod = types.ModuleType("custom_components.frigate_identity.person_registry")
    reg_mod.PersonData = object
    reg_mod.PersonRegistry = object

    sys.modules["custom_components"] = types.ModuleType("custom_components")
    pkg = types.ModuleType("custom_components.frigate_identity")
    pkg.__path__ = [str(MODULE_DIR)]
    sys.modules["custom_components.frigate_identity"] = pkg
    sys.modules["custom_components.frigate_identity.dashboard"] = dash_mod
    sys.modules["custom_components.frigate_identity.person_registry"] = reg_mod


def _load_integration_module():
    _stub_dependencies()

    const_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.const",
        MODULE_DIR / "const.py",
        submodule_search_locations=[],
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    sys.modules["custom_components.frigate_identity.const"] = const_mod
    const_spec.loader.exec_module(const_mod)

    init_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.__init__",
        MODULE_DIR / "__init__.py",
        submodule_search_locations=[],
    )
    init_mod = importlib.util.module_from_spec(init_spec)
    sys.modules["custom_components.frigate_identity.__init__"] = init_mod
    init_spec.loader.exec_module(init_mod)
    return init_mod


def test_build_false_positive_payload_uses_registry_event_context():
    mod = _load_integration_module()

    person = types.SimpleNamespace(event_id="evt-123", camera="front")
    registry = types.SimpleNamespace(get_person=lambda _name: person)

    payload = mod._build_false_positive_payload(registry, "Alice", 1001)
    parsed = json.loads(payload)

    assert parsed["person_id"] == "Alice"
    assert parsed["event_id"] == "evt-123"
    assert parsed["camera"] == "front"
    assert parsed["submitted_at"] == 1001


def test_async_submit_false_positive_publishes_expected_message():
    mod = _load_integration_module()

    mod.mqtt_component.async_publish = AsyncMock()
    registry = types.SimpleNamespace(
        get_person=lambda _name: types.SimpleNamespace(event_id="evt-9", camera="gate")
    )
    hass = types.SimpleNamespace(services=types.SimpleNamespace(async_call=AsyncMock()))

    asyncio.run(mod._async_submit_false_positive(hass, registry, "Bob"))

    assert mod.mqtt_component.async_publish.await_count == 1
    args = mod.mqtt_component.async_publish.await_args.args
    kwargs = mod.mqtt_component.async_publish.await_args.kwargs

    assert args[0] is hass
    assert args[1] == mod.TOPIC_FALSE_POSITIVE
    payload = json.loads(args[2])
    assert payload["person_id"] == "Bob"
    assert payload["event_id"] == "evt-9"
    assert payload["camera"] == "gate"
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is False


def test_async_submit_false_positive_publish_failure_notifies_operator():
    mod = _load_integration_module()

    mod.mqtt_component.async_publish = AsyncMock(side_effect=RuntimeError("broker down"))
    notify_call = AsyncMock()
    hass = types.SimpleNamespace(services=types.SimpleNamespace(async_call=notify_call))
    registry = types.SimpleNamespace(get_person=lambda _name: None)

    asyncio.run(mod._async_submit_false_positive(hass, registry, "Carol"))

    assert notify_call.await_count == 1
    call_args = notify_call.await_args.args
    call_data = notify_call.await_args.kwargs
    assert call_args[0] == "persistent_notification"
    assert call_args[1] == "create"
    data = call_args[2]
    assert data["notification_id"] == "fp_error_Carol"
    assert "Could not submit false positive" in data["message"]
    assert call_data == {}


def test_false_positive_notification_from_ack_success_and_error():
    mod = _load_integration_module()

    ok = {
        "person_id": "Dana",
        "status": "ok",
        "embeddings_removed": 2,
        "message": "",
    }
    err = {
        "person_id": "Dana",
        "status": "error",
        "message": "bad payload",
    }

    ok_title, ok_msg, ok_id = mod._false_positive_notification_from_ack(ok)
    assert ok_title == "False Positive Reported: Dana"
    assert "Removed 2 embedding(s)" in ok_msg
    assert ok_id == "fp_ok_Dana"

    err_title, err_msg, err_id = mod._false_positive_notification_from_ack(err)
    assert err_title == "False Positive Failed: Dana"
    assert err_msg == "bad payload"
    assert err_id == "fp_error_Dana"
