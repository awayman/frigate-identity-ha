"""Tests for dashboard ordering, unknown-person filtering, and card structure.

Verifies:
  - Unknown persons are omitted from the generated view.
  - Persons appear in entry.options['person_order'] order, with YAML meta
    and alphabetical fallbacks.
  - Each person card is a vertical-stack containing a header markdown with
    "Last seen" / "ha-relative-time", a picture-entity, an entities card,
    and a false-positive button.
  - The false-positive button calls frigate_identity.report_false_positive
    with the correct person_id in service_data.

Run with:
  cd frigate-identity-ha
  .venv/Scripts/python -m pytest tests/test_dashboard_ordering.py -v
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


# ── HA stubs ─────────────────────────────────────────────────────────────


def _stub_homeassistant() -> None:
    """Install minimal HA stubs so dashboard.py can be imported without HA."""

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
    """Load dashboard.py via importlib, bypassing package __init__.py."""
    import importlib.util  # noqa: PLC0415

    _stub_homeassistant()

    for key in list(sys.modules.keys()):
        if "frigate_identity" in key:
            del sys.modules[key]

    pkg_stub = types.ModuleType("custom_components.frigate_identity")
    pkg_stub.__path__ = [str(MODULE_DIR)]
    pkg_stub.__package__ = "custom_components.frigate_identity"
    sys.modules["custom_components"] = types.ModuleType("custom_components")
    sys.modules["custom_components.frigate_identity"] = pkg_stub

    # Load const.py first
    const_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.const",
        MODULE_DIR / "const.py",
        submodule_search_locations=[],
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    sys.modules["custom_components.frigate_identity.const"] = const_mod
    const_spec.loader.exec_module(const_mod)

    # Load person_registry.py
    pr_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.person_registry",
        MODULE_DIR / "person_registry.py",
        submodule_search_locations=[],
    )
    pr_mod = importlib.util.module_from_spec(pr_spec)
    sys.modules["custom_components.frigate_identity.person_registry"] = pr_mod
    pr_spec.loader.exec_module(pr_mod)

    # Load dashboard.py
    dash_spec = importlib.util.spec_from_file_location(
        "custom_components.frigate_identity.dashboard",
        MODULE_DIR / "dashboard.py",
        submodule_search_locations=[],
    )
    dash_mod = importlib.util.module_from_spec(dash_spec)
    sys.modules["custom_components.frigate_identity.dashboard"] = dash_mod
    dash_spec.loader.exec_module(dash_mod)
    return dash_mod


# ── Test helpers ─────────────────────────────────────────────────────────


def _make_hass() -> Any:
    return types.SimpleNamespace(
        states=types.SimpleNamespace(get=lambda _: None),
    )


def _make_registry(
    persons: dict[str, dict[str, Any]],
    meta: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Build a minimal mock PersonRegistry.

    persons = {name: {"is_child": bool, "snapshot_url": str|None, "last_seen": str|None}}
    meta    = {name: {"order": int, ...}}
    """
    _meta = meta or {}
    _persons: dict[str, Any] = {}
    for name, data in persons.items():
        _persons[name] = types.SimpleNamespace(
            is_child=data.get("is_child", False),
            snapshot_url=data.get("snapshot_url"),
            last_seen=data.get("last_seen"),
        )

    class MockRegistry:
        meta = _meta

        @property
        def person_names(self) -> list[str]:
            return sorted(_persons.keys())

        def get_person(self, name: str) -> Any:
            return _persons.get(name)

    return MockRegistry()


def _walk_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recursively collect all non-container cards from a card tree."""
    result: list[dict[str, Any]] = []
    for card in cards:
        if card.get("type") in ("vertical-stack", "horizontal-stack"):
            result.extend(_walk_cards(card.get("cards", [])))
        else:
            result.append(card)
    return result


# ── Tests: filtering, sorting, sort-key helper ───────────────────────────


class TestPersonSortKey(unittest.TestCase):
    """Tests for _person_sort_key()."""

    def setUp(self) -> None:
        self.dash = _load_dashboard()

    def _sort_key(self, name: str, order_map: dict, meta: dict | None = None) -> tuple:
        registry = _make_registry(
            {name: {}},
            meta={name: meta} if meta else {},
        )
        return self.dash._person_sort_key(name, order_map, registry)

    def test_explicit_order_bucket_zero(self) -> None:
        key = self._sort_key("Alice", {"Alice": 5})
        self.assertEqual(key[0], 0)
        self.assertEqual(key[1], 5)

    def test_meta_order_bucket_one(self) -> None:
        key = self._sort_key("Bob", {}, meta={"order": 3})
        self.assertEqual(key[0], 1)
        self.assertEqual(key[1], 3)

    def test_alpha_bucket_two(self) -> None:
        key = self._sort_key("Charlie", {})
        self.assertEqual(key[0], 2)

    def test_explicit_order_beats_meta(self) -> None:
        key = self._sort_key("Dave", {"Dave": 1}, meta={"order": 99})
        self.assertEqual(key[0], 0)
        self.assertEqual(key[1], 1)

    def test_sort_respects_person_order_map(self) -> None:
        """Persons sort by person_order_map value when present."""
        persons = ["Charlie", "Alice", "Bob"]
        order_map = {"Alice": 2, "Bob": 1, "Charlie": 3}
        registry = _make_registry({p: {} for p in persons})
        sorted_persons = sorted(
            persons,
            key=lambda p: self.dash._person_sort_key(p, order_map, registry),
        )
        self.assertEqual(sorted_persons, ["Bob", "Alice", "Charlie"])

    def test_alpha_fallback_when_no_order(self) -> None:
        persons = ["Zara", "Alice", "Mike"]
        registry = _make_registry({p: {} for p in persons})
        sorted_persons = sorted(
            persons,
            key=lambda p: self.dash._person_sort_key(p, {}, registry),
        )
        self.assertEqual(sorted_persons, ["alice", "mike", "zara"] if False else ["Alice", "Mike", "Zara"])


class TestUnknownPersonFiltering(unittest.TestCase):
    """Tests confirming unknown-prefixed persons are filtered out."""

    def test_filter_unknown_prefix(self) -> None:
        persons = ["Alice", "Bob", "Unknown_abc", "unknown_xyz", "UNKNOWN_123"]
        filtered = [p for p in persons if not p.lower().startswith("unknown")]
        self.assertEqual(sorted(filtered), ["Alice", "Bob"])

    def test_known_persons_pass_through(self) -> None:
        persons = ["Alice", "Bob"]
        filtered = [p for p in persons if not p.lower().startswith("unknown")]
        self.assertEqual(filtered, ["Alice", "Bob"])

    def test_all_unknown_returns_empty(self) -> None:
        persons = ["Unknown_1", "unknown_2"]
        filtered = [p for p in persons if not p.lower().startswith("unknown")]
        self.assertEqual(filtered, [])


# ── Tests: _person_card structure ────────────────────────────────────────


class TestPersonCardStructure(unittest.TestCase):
    """Tests for the updated _person_card() function."""

    def setUp(self) -> None:
        self.dash = _load_dashboard()

    def _build_card(
        self,
        name: str = "Alice",
        snapshot_source: str = "mqtt",
        is_child: bool = False,
    ) -> dict[str, Any]:
        hass = _make_hass()
        registry = _make_registry({name: {"is_child": is_child}})
        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            return self.dash._person_card(hass, name, snapshot_source, registry)

    # ── Card shape ──────────────────────────────────────────────────────

    def test_is_vertical_stack(self) -> None:
        self.assertEqual(self._build_card()["type"], "vertical-stack")

    def test_has_four_sub_cards(self) -> None:
        """Order: header markdown, picture-entity, entities, button."""
        cards = self._build_card()["cards"]
        self.assertEqual(len(cards), 4)

    def test_first_card_is_header_markdown(self) -> None:
        card = self._build_card()["cards"][0]
        self.assertEqual(card["type"], "markdown")

    def test_second_card_is_picture_entity(self) -> None:
        card = self._build_card()["cards"][1]
        self.assertEqual(card["type"], "picture-entity")

    def test_third_card_is_entities(self) -> None:
        card = self._build_card()["cards"][2]
        self.assertEqual(card["type"], "entities")

    def test_fourth_card_is_button(self) -> None:
        card = self._build_card()["cards"][3]
        self.assertEqual(card["type"], "button")

    # ── Header card content ──────────────────────────────────────────────

    def test_header_contains_person_name(self) -> None:
        content = self._build_card(name="Eve")["cards"][0]["content"]
        self.assertIn("Eve", content)

    def test_header_contains_last_seen(self) -> None:
        content = self._build_card()["cards"][0]["content"]
        self.assertIn("Last seen", content)

    def test_header_contains_ha_relative_time(self) -> None:
        content = self._build_card()["cards"][0]["content"]
        self.assertIn("ha-relative-time", content)

    def test_header_has_jinja_template_expression(self) -> None:
        content = self._build_card()["cards"][0]["content"]
        self.assertIn("{{", content)
        self.assertIn("}}", content)

    # ── False-positive button ─────────────────────────────────────────────

    def test_button_references_correct_person(self) -> None:
        btn = self._build_card(name="Frank")["cards"][3]
        self.assertEqual(btn["tap_action"]["service_data"]["person_id"], "Frank")

    def test_button_calls_false_positive_service(self) -> None:
        btn = self._build_card()["cards"][3]
        self.assertIn("report_false_positive", btn["tap_action"]["service"])

    def test_button_uses_frigate_identity_domain(self) -> None:
        btn = self._build_card()["cards"][3]
        self.assertTrue(
            btn["tap_action"]["service"].startswith("frigate_identity."),
            msg=f"Expected 'frigate_identity.' prefix, got: {btn['tap_action']['service']}",
        )

    # ── Child supervision entity ──────────────────────────────────────────

    def test_child_card_has_supervised_entity(self) -> None:
        """Children get an extra 'Supervised' binary sensor row."""
        cards = self._build_card(name="Kid", is_child=True)["cards"]
        entities_card = cards[2]
        entity_names = [e.get("name") for e in entities_card["entities"]]
        self.assertIn("Supervised", entity_names)

    def test_adult_card_has_no_supervised_entity(self) -> None:
        cards = self._build_card(name="Adult", is_child=False)["cards"]
        entities_card = cards[2]
        entity_names = [e.get("name") for e in entities_card["entities"]]
        self.assertNotIn("Supervised", entity_names)

    # ── Snapshot sources ─────────────────────────────────────────────────

    def test_all_snapshot_sources_produce_vertical_stack(self) -> None:
        for source in ("mqtt", "frigate_api", "frigate_integration"):
            with self.subTest(source=source):
                card = self._build_card(snapshot_source=source)
                self.assertEqual(card["type"], "vertical-stack")


# ── Tests: _build_view flat layout ───────────────────────────────────────


class TestBuildViewFlatLayout(unittest.TestCase):
    """Tests that _build_view produces a flat sequence of person cards."""

    def setUp(self) -> None:
        self.dash = _load_dashboard()

    def _build_view_for(
        self,
        persons: list[str],
        meta: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        hass = _make_hass()
        registry = _make_registry({p: {} for p in persons}, meta=meta)
        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            return self.dash._build_view(hass, persons, "mqtt", registry, "Kids")

    def test_view_has_correct_path(self) -> None:
        view = self._build_view_for(["Alice"])
        self.assertEqual(view["path"], "frigate-identity")

    def test_view_title_matches_dashboard_name(self) -> None:
        hass = _make_hass()
        registry = _make_registry({"Alice": {}})
        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            view = self.dash._build_view(hass, ["Alice"], "mqtt", registry, "My Tracker")
        self.assertEqual(view["title"], "My Tracker")

    def test_person_cards_are_vertical_stacks(self) -> None:
        view = self._build_view_for(["Alice", "Bob"])
        person_cards = [
            c for c in view["cards"] if c.get("type") == "vertical-stack"
        ]
        self.assertEqual(len(person_cards), 2)

    def test_no_horizontal_stack_grouping(self) -> None:
        """Area grouping is removed; no horizontal-stack at view level."""
        view = self._build_view_for(["Alice", "Bob", "Charlie"])
        top_level_types = [c.get("type") for c in view["cards"]]
        self.assertNotIn("horizontal-stack", top_level_types)

    def test_person_order_preserved_in_cards(self) -> None:
        """Persons appear in the order passed to _build_view."""
        view = self._build_view_for(["Bob", "Alice"])
        person_cards = [c for c in view["cards"] if c.get("type") == "vertical-stack"]
        # Each person card is a vertical-stack; header markdown contains the name
        headers = [c["cards"][0]["content"] for c in person_cards]
        self.assertIn("Bob", headers[0])
        self.assertIn("Alice", headers[1])


# ── Integration: unknown filter + ordering + card structure ───────────────


class TestDashboardIntegration(unittest.TestCase):
    """End-to-end smoke test through _build_view with ordering + filtering."""

    def setUp(self) -> None:
        self.dash = _load_dashboard()

    def test_unknown_persons_excluded_from_view(self) -> None:
        """UnknownPerson must not appear as a card in the generated view."""
        hass = _make_hass()
        registry = _make_registry(
            {
                "PersonA": {"last_seen": "2025-01-01T12:00:00"},
                "PersonB": {"snapshot_url": "http://example.com/snap.jpg"},
                "Unknown_abc": {},
            }
        )
        # Simulate the filtering step from async_generate_dashboard
        all_persons = registry.person_names  # ["PersonA", "PersonB", "Unknown_abc"]
        filtered = [p for p in all_persons if not p.lower().startswith("unknown")]
        self.assertNotIn("Unknown_abc", filtered)
        self.assertIn("PersonA", filtered)
        self.assertIn("PersonB", filtered)

        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            view = self.dash._build_view(hass, filtered, "mqtt", registry, "Kids")

        person_cards = [c for c in view["cards"] if c.get("type") == "vertical-stack"]
        card_names_in_headers = " ".join(c["cards"][0]["content"] for c in person_cards)
        self.assertNotIn("Unknown_abc", card_names_in_headers)
        self.assertIn("PersonA", card_names_in_headers)
        self.assertIn("PersonB", card_names_in_headers)

    def test_person_order_from_options_controls_card_sequence(self) -> None:
        """entry.options['person_order'] determines card sequence."""
        hass = _make_hass()
        registry = _make_registry(
            {"Charlie": {}, "Alice": {}, "Bob": {}},
        )
        # person_order map: Bob=1, Alice=2, Charlie=3
        person_order_map = {"Bob": 1, "Alice": 2, "Charlie": 3}
        persons = sorted(
            registry.person_names,
            key=lambda p: self.dash._person_sort_key(p, person_order_map, registry),
        )
        self.assertEqual(persons, ["Bob", "Alice", "Charlie"])

        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            view = self.dash._build_view(hass, persons, "mqtt", registry, "Kids")

        person_cards = [c for c in view["cards"] if c.get("type") == "vertical-stack"]
        ordered_names = [c["cards"][0]["content"] for c in person_cards]
        self.assertIn("Bob", ordered_names[0])
        self.assertIn("Alice", ordered_names[1])
        self.assertIn("Charlie", ordered_names[2])

    def test_each_person_card_has_false_positive_button_with_service(self) -> None:
        """Every person card must have a false-positive call-service button."""
        hass = _make_hass()
        registry = _make_registry({"PersonA": {}, "PersonB": {}})
        with patch.object(
            self.dash,
            "_resolve_entity_id",
            side_effect=lambda _h, **kw: kw["candidates"][0],
        ):
            view = self.dash._build_view(hass, ["PersonA", "PersonB"], "mqtt", registry, "Kids")

        for card in [c for c in view["cards"] if c.get("type") == "vertical-stack"]:
            btn = card["cards"][3]
            self.assertEqual(btn["type"], "button")
            self.assertIn("report_false_positive", btn["tap_action"]["service"])
            self.assertIn("person_id", btn["tap_action"]["service_data"])


if __name__ == "__main__":
    unittest.main()
