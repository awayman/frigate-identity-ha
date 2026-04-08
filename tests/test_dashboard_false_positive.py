"""Tests for the false-positive dashboard control in dashboard.py.

Tests verify that:
  - _false_positive_button() returns a correctly structured button card.
  - _person_card() includes the false-positive button in its vertical-stack.
  - The service call in the button uses the correct domain and service name.

Run with:
  cd frigate-identity-ha
  .venv/Scripts/python -m pytest tests/test_dashboard_false_positive.py -v
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = REPO_ROOT / "custom_components" / "frigate_identity"


def _stub_homeassistant():
    """Install minimal HA stubs so dashboard.py and person_registry.py can be imported without HA."""

    class _HomeAssistant:  # noqa: N801
        pass

    def _callback(func):
        return func

    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = _HomeAssistant
    ha_core.callback = _callback
    ha_core.ServiceCall = object

    ha_ar = types.ModuleType("homeassistant.helpers.area_registry")
    ha_ar.async_get = lambda _hass: types.SimpleNamespace(areas={})
    ha_ar.AreaRegistry = object

    ha_er = types.ModuleType("homeassistant.helpers.entity_registry")
    ha_er.async_get = lambda _hass: types.SimpleNamespace(entities={})
    ha_er.EntityRegistry = object

    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_helpers.area_registry = ha_ar
    ha_helpers.entity_registry = ha_er

    ha_lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    ha_lovelace_const.ConfigNotFound = Exception

    ha_lovelace = types.ModuleType("homeassistant.components.lovelace")
    ha_lovelace.const = ha_lovelace_const

    ha_frontend = types.ModuleType("homeassistant.components.frontend")
    ha_components = types.ModuleType("homeassistant.components")
    ha_components.frontend = ha_frontend
    ha_components.lovelace = ha_lovelace
    ha_root = types.ModuleType("homeassistant")
    ha_root.core = ha_core
    ha_root.components = ha_components
    ha_root.helpers = ha_helpers

    stubs = {
        "homeassistant": ha_root,
        "homeassistant.components": ha_components,
        "homeassistant.components.frontend": ha_frontend,
        "homeassistant.components.lovelace": ha_lovelace,
        "homeassistant.components.lovelace.const": ha_lovelace_const,
        "homeassistant.core": ha_core,
        "homeassistant.helpers": ha_helpers,
        "homeassistant.helpers.area_registry": ha_ar,
        "homeassistant.helpers.entity_registry": ha_er,
    }
    for mod_name, mod in stubs.items():
        sys.modules[mod_name] = mod


def _load_dashboard():
    """Load dashboard.py directly via importlib, bypassing __init__.py."""
    import importlib.util  # noqa: PLC0415

    _stub_homeassistant()

    # Remove any cached module so we get a fresh import each call
    for key in list(sys.modules.keys()):
        if "frigate_identity" in key:
            del sys.modules[key]

    # Pre-register stub for the package itself so relative imports inside
    # const.py / dashboard.py resolve without executing __init__.py
    pkg_stub = types.ModuleType("custom_components.frigate_identity")
    pkg_stub.__path__ = [str(MODULE_DIR)]
    pkg_stub.__package__ = "custom_components.frigate_identity"
    sys.modules["custom_components"] = types.ModuleType("custom_components")
    sys.modules["custom_components.frigate_identity"] = pkg_stub

    # Load const.py first (no heavy deps)
    const_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.const",
        MODULE_DIR / "const.py",
        submodule_search_locations=[],
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    sys.modules["custom_components.frigate_identity.const"] = const_mod
    const_spec.loader.exec_module(const_mod)

    # Now load dashboard.py
    # Load person_registry.py (needed by dashboard.py)
    pr_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.person_registry",
        MODULE_DIR / "person_registry.py",
        submodule_search_locations=[],
    )
    pr_mod = importlib.util.module_from_spec(pr_spec)
    sys.modules["custom_components.frigate_identity.person_registry"] = pr_mod
    pr_spec.loader.exec_module(pr_mod)

    # Now load dashboard.py
    dash_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.dashboard",
        MODULE_DIR / "dashboard.py",
        submodule_search_locations=[],
    )
    dash_mod = importlib.util.module_from_spec(dash_spec)
    sys.modules["custom_components.frigate_identity.dashboard"] = dash_mod
    dash_spec.loader.exec_module(dash_mod)
    return dash_mod


class TestFalsePositiveButton(unittest.TestCase):
    """Tests for the _false_positive_button() helper."""

    def setUp(self):
        self.dash = _load_dashboard()

    def test_returns_button_type(self):
        card = self.dash._false_positive_button("Alice")
        self.assertEqual(card["type"], "button")

    def test_button_name(self):
        card = self.dash._false_positive_button("Alice")
        self.assertIn("False Positive", card["name"])

    def test_tap_action_calls_service(self):
        card = self.dash._false_positive_button("Alice")
        tap = card["tap_action"]
        self.assertEqual(tap["action"], "call-service")
        self.assertIn("report_false_positive", tap["service"])

    def test_service_data_contains_person_id(self):
        card = self.dash._false_positive_button("Bob")
        self.assertEqual(card["tap_action"]["service_data"]["person_id"], "Bob")

    def test_button_has_icon(self):
        card = self.dash._false_positive_button("Carol")
        self.assertIn("icon", card)

    def test_service_uses_correct_domain(self):
        """Service call must reference the frigate_identity domain."""
        card = self.dash._false_positive_button("Dave")
        service = card["tap_action"]["service"]
        self.assertTrue(
            service.startswith("frigate_identity."),
            msg=f"Expected 'frigate_identity.' prefix, got: {service}",
        )


class TestPersonCardIncludesButton(unittest.TestCase):
    """Tests that _person_card() embeds the false-positive button."""

    def setUp(self):
        self.dash = _load_dashboard()

    def _make_hass(self):
        return types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda _: None),
        )

    def _make_registry(self, is_child: bool = False):
        person = types.SimpleNamespace(is_child=is_child)
        return types.SimpleNamespace(
            meta={},
            get_person=lambda _name: person,
        )

    def _build_card(self, name: str = "Alice", snapshot_source: str = "mqtt"):
        hass = self._make_hass()
        registry = self._make_registry()
        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            return self.dash._person_card(hass, name, snapshot_source, registry)

    def test_card_is_single_wrapped_card(self):
        card = self._build_card()
        self.assertEqual(card["type"], "custom:stack-in-card")

    def test_stack_contains_button(self):
        card = self._build_card()
        types_in_stack = [c.get("type") for c in card["cards"]]
        self.assertIn("button", types_in_stack)

    def test_button_references_correct_person(self):
        card = self._build_card(name="Eve")
        btn = next(c for c in card["cards"] if c.get("type") == "button")
        self.assertEqual(btn["tap_action"]["service_data"]["person_id"], "Eve")

    def test_button_present_for_child(self):
        """Children also get a false-positive button."""
        hass = self._make_hass()
        registry = self._make_registry(is_child=True)
        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            card = self.dash._person_card(hass, "Kid", "mqtt", registry)
        types_in_stack = [c.get("type") for c in card["cards"]]
        self.assertIn("button", types_in_stack)

    def test_all_snapshot_sources_get_button(self):
        for source in ("mqtt", "frigate_api", "frigate_integration"):
            with self.subTest(source=source):
                card = self._build_card(snapshot_source=source)
                types_in_stack = [c.get("type") for c in card["cards"]]
                self.assertIn(
                    "button",
                    types_in_stack,
                    msg=f"Button missing for snapshot_source={source}",
                )


if __name__ == "__main__":
    unittest.main()
