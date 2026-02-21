"""Dashboard generation for Frigate Identity.

Builds a Lovelace view and pushes it to HA's storage-mode dashboard.
Absorbs the dashboard-building logic from examples/generate_dashboard.py
so it runs inside the integration — no external script or AppDaemon needed.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er

from .const import (
    CONF_SNAPSHOT_SOURCE,
    DEFAULT_SNAPSHOT_SOURCE,
    SNAPSHOT_SOURCE_FRIGATE_API,
    SNAPSHOT_SOURCE_FRIGATE_INTEGRATION,
    SNAPSHOT_SOURCE_MQTT,
)
from .person_registry import PersonRegistry, is_child

_LOGGER = logging.getLogger(__name__)


def _slug(name: str) -> str:
    """Return a lowercase underscore slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


# ── Card builders ───────────────────────────────────────────────────────


def _snapshot_entity_id(person: str, snapshot_source: str) -> str:
    """Return the HA entity ID for this person's snapshot."""
    slug = _slug(person)
    if snapshot_source == SNAPSHOT_SOURCE_MQTT:
        return f"camera.frigate_identity_{slug}_snapshot"
    if snapshot_source == SNAPSHOT_SOURCE_FRIGATE_API:
        return f"image.frigate_identity_{slug}_snapshot_image"
    # frigate_integration
    return f"image.{slug}_person"


def _person_card(
    person: str,
    snapshot_source: str,
    registry: PersonRegistry,
) -> dict[str, Any]:
    """Build a vertical-stack card for one person."""
    slug = _slug(person)
    location_entity = f"sensor.frigate_identity_{slug}_location"
    snap_entity = _snapshot_entity_id(person, snapshot_source)

    snapshot_card: dict[str, Any] = {
        "type": "picture-entity",
        "entity": snap_entity,
        "name": f"{person} – Latest Snapshot",
        "show_state": False,
        "show_name": True,
    }

    status_entities: list[dict[str, Any]] = [
        {"entity": location_entity, "name": "Location"},
        {"type": "attribute", "entity": location_entity, "attribute": "zones", "name": "Zones"},
        {"type": "attribute", "entity": location_entity, "attribute": "confidence", "name": "Confidence"},
        {"type": "attribute", "entity": location_entity, "attribute": "source", "name": "Source"},
        {"type": "attribute", "entity": location_entity, "attribute": "last_seen", "name": "Last Seen"},
    ]

    if is_child(registry.meta.get(person, {})):
        status_entities.insert(
            1,
            {
                "entity": f"binary_sensor.frigate_identity_{slug}_supervised",
                "name": "Supervised",
            },
        )

    status_card: dict[str, Any] = {
        "type": "entities",
        "title": f"{person} Status",
        "entities": status_entities,
    }

    return {"type": "vertical-stack", "cards": [snapshot_card, status_card]}


def _area_icon(area_name: str) -> str:
    """Pick an icon for an area name."""
    lower = area_name.lower()
    if any(w in lower for w in ("yard", "garden", "outdoor", "outside", "back", "front")):
        return "🌳"
    if any(w in lower for w in ("entry", "door", "drive", "garage")):
        return "🚗"
    if any(w in lower for w in ("living", "lounge", "kitchen", "bed", "bath")):
        return "🏡"
    return "🏠"


def _area_section(
    area_name_str: str,
    persons_in_area: list[str],
    snapshot_source: str,
    registry: PersonRegistry,
) -> list[dict[str, Any]]:
    """Build cards for one area section."""
    icon = _area_icon(area_name_str)
    cards: list[dict[str, Any]] = [
        {"type": "markdown", "content": f"## {icon} {area_name_str}"}
    ]

    person_cards = [
        _person_card(p, snapshot_source, registry) for p in persons_in_area
    ]
    if len(person_cards) > 1:
        cards.append({"type": "horizontal-stack", "cards": person_cards})
    elif person_cards:
        cards.append(person_cards[0])

    return cards


# ── View builder ────────────────────────────────────────────────────────


def _build_view(
    persons: list[str],
    snapshot_source: str,
    registry: PersonRegistry,
    area_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a complete Lovelace view dict."""
    header_card: dict[str, Any] = {
        "type": "markdown",
        "content": (
            "# 📍 Frigate Identity – Person Tracker\n"
            "Real-time location and bounded snapshot for each tracked person."
        ),
    }
    summary_card: dict[str, Any] = {
        "type": "entities",
        "title": "System Status",
        "entities": [
            {"entity": "sensor.frigate_identity_all_persons", "name": "Persons Currently Tracked"},
            {"entity": "sensor.frigate_identity_last_person", "name": "Last Detection"},
        ],
    }

    body_cards: list[dict[str, Any]] = []

    if area_map:
        # Group persons by area
        person_area: dict[str, str] = {}
        for person in persons:
            meta = registry.meta.get(person, {})
            cam = meta.get("camera", _slug(person))
            person_area[person] = area_map.get(cam, "")

        seen: set[str] = set()
        ordered_areas: list[str] = []
        for person in persons:
            a = person_area[person]
            if a and a not in seen:
                seen.add(a)
                ordered_areas.append(a)

        for area in ordered_areas:
            ppl = [p for p in persons if person_area[p] == area]
            body_cards.extend(
                _area_section(area, ppl, snapshot_source, registry)
            )

        unassigned = [p for p in persons if not person_area[p]]
        if unassigned:
            body_cards.extend(
                _area_section("Unassigned", unassigned, snapshot_source, registry)
            )
    else:
        body_cards = [
            _person_card(p, snapshot_source, registry) for p in persons
        ]

    return {
        "title": "Frigate Identity",
        "path": "frigate-identity",
        "icon": "mdi:account-search",
        "cards": [header_card, *body_cards, summary_card],
    }


# ── Area map helpers ────────────────────────────────────────────────────


async def _fetch_area_map(hass: HomeAssistant) -> dict[str, str]:
    """Build a camera→area mapping from HA registries."""
    result: dict[str, str] = {}
    try:
        ent_reg = er.async_get(hass)
        a_reg = ar.async_get(hass)

        for entry in ent_reg.entities.values():
            if entry.domain != "camera":
                continue
            if entry.area_id:
                area = a_reg.async_get_area(entry.area_id)
                if area:
                    # Strip "camera." prefix to get camera name
                    cam_name = entry.entity_id.removeprefix("camera.")
                    result[cam_name] = area.name
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not fetch camera area assignments")

    return result


# ── Public API ──────────────────────────────────────────────────────────


async def async_generate_dashboard(
    hass: HomeAssistant,
    registry: PersonRegistry,
    config: dict[str, Any],
) -> bool:
    """Generate and push the Frigate Identity Lovelace view.

    Returns True on success, False on failure.
    """
    persons = registry.person_names
    if not persons:
        _LOGGER.debug("No persons registered; skipping dashboard generation")
        return False

    snapshot_source = config.get(CONF_SNAPSHOT_SOURCE, DEFAULT_SNAPSHOT_SOURCE)

    # Merge camera_zones overrides with HA area assignments
    ha_areas = await _fetch_area_map(hass)
    area_map = {**ha_areas, **registry.camera_zones}

    view = _build_view(persons, snapshot_source, registry, area_map or None)

    # Push to Lovelace storage
    try:
        lovelace = hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.warning(
                "Lovelace data not available; cannot push dashboard. "
                "This may happen if HA uses YAML-mode dashboards."
            )
            return False

        # Get the config object from the lovelace integration
        config_obj = lovelace.get("config")
        if config_obj is None:
            _LOGGER.debug("No lovelace config object found; trying direct approach")
            return await _push_via_ws(hass, view)

        current = await config_obj.async_load(False)
        views: list[dict[str, Any]] = list(current.get("views", []))
        views = [v for v in views if v.get("path") != "frigate-identity"]
        views.append(view)
        current["views"] = views
        await config_obj.async_save(current)
        _LOGGER.info("Frigate Identity dashboard view updated successfully")
        return True

    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "Could not push via lovelace storage; trying websocket approach"
        )
        return await _push_via_ws(hass, view)


async def _push_via_ws(
    hass: HomeAssistant, view: dict[str, Any]
) -> bool:
    """Push dashboard view using the websocket-style lovelace API."""
    try:
        from homeassistant.components.lovelace import dashboard as ll_dashboard

        for dashboard_obj in hass.data.get("lovelace_dashboards", {}).values():
            if hasattr(dashboard_obj, "config") and dashboard_obj.config is not None:
                config = dashboard_obj.config
                if hasattr(config, "async_load"):
                    current = await config.async_load(False)
                    if isinstance(current, dict):
                        views = list(current.get("views", []))
                        views = [
                            v for v in views if v.get("path") != "frigate-identity"
                        ]
                        views.append(view)
                        current["views"] = views
                        await config.async_save(current)
                        _LOGGER.info(
                            "Dashboard view pushed via lovelace_dashboards"
                        )
                        return True
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Failed to push Frigate Identity dashboard. "
            "You may need to paste the view YAML manually."
        )

    return False
