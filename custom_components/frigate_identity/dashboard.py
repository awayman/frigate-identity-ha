"""Dashboard generation for Frigate Identity.

Builds a Lovelace view and pushes it to HA's storage-mode dashboard.
Absorbs the dashboard-building logic from examples/generate_dashboard.py
so it runs inside the integration — no external script or AppDaemon needed.
"""
from __future__ import annotations

import json
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
from .person_registry import PersonRegistry

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

    # Check if child using the registry person data
    person_obj = registry.get_person(person)
    if person_obj and person_obj.is_child:
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
    _LOGGER.debug("=== DASHBOARD GENERATION STARTED ===")
    persons = registry.person_names
    _LOGGER.debug("Persons in registry: %d - %s", len(persons), persons)
    
    if not persons:
        _LOGGER.warning("No persons registered; skipping dashboard generation")
        _LOGGER.warning("Dashboard cannot be created without persons!")
        return False

    snapshot_source = config.get(CONF_SNAPSHOT_SOURCE, DEFAULT_SNAPSHOT_SOURCE)
    _LOGGER.debug("Snapshot source: %s", snapshot_source)

    # Merge camera_zones overrides with HA area assignments
    ha_areas = await _fetch_area_map(hass)
    area_map = {**ha_areas, **registry.camera_zones}
    _LOGGER.debug("Area map loaded: %d areas", len(area_map) if area_map else 0)

    view = _build_view(persons, snapshot_source, registry, area_map or None)
    _LOGGER.debug("Dashboard view built with %d cards", len(view.get("cards", [])))

    # Push to Lovelace storage
    _LOGGER.debug(
        "Attempting to push dashboard: lovelace_available=%s, "
        "persons=%d, snapshot_source=%s",
        "lovelace" in hass.data,
        len(persons),
        snapshot_source,
    )
    _LOGGER.debug("Available hass.data keys: %s", list(hass.data.keys()))
    try:
        # Try accessing lovelace_dashboards (modern HA approach)
        dashboards = hass.data.get("lovelace_dashboards", {})
        _LOGGER.debug("Found %d lovelace_dashboards in hass.data", len(dashboards))
        if dashboards:
            _LOGGER.debug("Dashboard keys: %s", list(dashboards.keys()))
        
        if not dashboards:
            _LOGGER.debug(
                "No lovelace_dashboards found in hass.data; "
                "will try HA 2026 API (lovelace.dashboards)..."
            )
            _LOGGER.debug("Trying alternative lovelace access method...")
            
            # Try alternative access method for HA 2026+
            lovelace_storage = hass.data.get("lovelace")
            if lovelace_storage:
                _LOGGER.debug("Found 'lovelace' in hass.data, attempting alternative method")
                _LOGGER.debug("Lovelace object type: %s", type(lovelace_storage).__name__)
                
                try:
                    # Log available methods
                    available_attrs = [attr for attr in dir(lovelace_storage) if not attr.startswith('_')]
                    _LOGGER.debug("Lovelace object has these attributes: %s", available_attrs)
                    
                    # HA 2026: lovelace.dashboards replaces lovelace_dashboards
                    if hasattr(lovelace_storage, "dashboards"):
                        _LOGGER.debug("✓ Has dashboards attribute (HA 2026 API)")
                        dashboards_obj = lovelace_storage.dashboards
                        _LOGGER.debug("  dashboards type: %s", type(dashboards_obj).__name__)
                        
                        # Try to find the default dashboard
                        for dash_key in [None, "lovelace"]:
                            if dash_key in dashboards_obj:
                                dashboard = dashboards_obj[dash_key]
                                _LOGGER.debug("  Found dashboard with key '%s'", dash_key)
                                _LOGGER.debug("    Dashboard type: %s", type(dashboard).__name__)
                                
                                # HA 2026: LovelaceStorage has async_load/async_save directly
                                if hasattr(dashboard, "async_load"):
                                    _LOGGER.debug("    ✓ Has async_load directly on dashboard object")
                                    try:
                                        current = await dashboard.async_load(False)
                                        _LOGGER.debug("    async_load returned: type=%s, value=%s", type(current).__name__, current if not isinstance(current, dict) else "dict")
                                        if isinstance(current, dict):
                                            views = list(current.get("views", []))
                                            views = [v for v in views if v.get("path") != "frigate-identity"]
                                            views.append(view)
                                            current["views"] = views
                                            if hasattr(dashboard, "async_save"):
                                                await dashboard.async_save(current)
                                                _LOGGER.info("✅ Dashboard updated via LovelaceStorage.async_load/save (HA 2026)!")
                                                return True
                                        else:
                                            _LOGGER.info("    async_load returned non-dict: %s", type(current).__name__)
                                    except Exception as e:
                                        _LOGGER.debug("Exception updating dashboard '%s': %s", dash_key, str(e))
                                        continue  # Try next dashboard
                                else:
                                    _LOGGER.debug("    ✗ No async_load method")
                        
                        # If main dashboard not updated, create a dedicated Frigate Identity dashboard
                        _LOGGER.debug("  Creating dedicated 'frigate-identity' dashboard...")
                        
                        # Try to create a new dedicated dashboard for Frigate Identity
                        if "frigate-identity" not in dashboards_obj:
                            _LOGGER.debug("    'frigate-identity' dashboard doesn't exist, will create one")
                            try:
                                from homeassistant.components.lovelace.dashboard import LovelaceStorage
                                
                                # Create the dashboard config with our view as the only view
                                dashboard_config = {
                                    "views": [view]
                                }
                                
                                # LovelaceStorage signature is: __init__(hass, config)
                                new_dashboard = LovelaceStorage(hass, dashboard_config)
                                dashboards_obj["frigate-identity"] = new_dashboard
                                
                                _LOGGER.info("✅ Created dedicated 'frigate-identity' dashboard as separate tab!")
                                return True
                            except Exception as e:
                                _LOGGER.error("Could not create dedicated dashboard: %s", str(e), exc_info=True)
                                _LOGGER.warning("Dashboard will not be created. Consider creating a 'Frigate Identity' dashboard manually in Settings → Dashboards")
                                return False
                        else:
                            # Dashboard already exists, add view to it
                            try:
                                dashboard = dashboards_obj["frigate-identity"]
                                if hasattr(dashboard, "async_load"):
                                    current = await dashboard.async_load(False)
                                    if isinstance(current, dict):
                                        views = list(current.get("views", []))
                                        views = [v for v in views if v.get("path") != "frigate-identity"]
                                        views.append(view)
                                        current["views"] = views
                                        await dashboard.async_save(current)
                                        _LOGGER.info("✅ Updated 'frigate-identity' dashboard!")
                                        return True
                            except Exception as e:
                                _LOGGER.error("Could not update existing dashboard: %s", str(e), exc_info=True)
                    
                    _LOGGER.error("Could not find compatible method to update dashboard in HA 2026")
                    
                except Exception:
                    _LOGGER.exception("Exception while trying alternative lovelace access")
            else:
                _LOGGER.warning("'lovelace' key not found in hass.data")
            
            return False
        
        # Try to find the main dashboard (usually key is None or "lovelace")
        for dash_key in [None, "lovelace"]:
            if dash_key in dashboards:
                dashboard_obj = dashboards[dash_key]
                _LOGGER.info(
                    "Found dashboard with key '%s' (type=%s)",
                    dash_key,
                    type(dashboard_obj).__name__,
                )
                
                if hasattr(dashboard_obj, "config") and dashboard_obj.config is not None:
                    config_obj = dashboard_obj.config
                    if hasattr(config_obj, "async_load"):
                        _LOGGER.info("Loading current dashboard config")
                        current = await config_obj.async_load(False)
                        
                        if isinstance(current, dict):
                            views: list[dict[str, Any]] = list(current.get("views", []))
                            _LOGGER.info("Current dashboard has %d view(s)", len(views))
                            views = [v for v in views if v.get("path") != "frigate-identity"]
                            views.append(view)
                            current["views"] = views
                            await config_obj.async_save(current)
                            _LOGGER.info("Frigate Identity dashboard view updated successfully")
                            return True
                else:
                    _LOGGER.warning("Dashboard object missing 'config' attribute or has method signature changes")
        
        # If we didn't find the main dashboard, try all dashboards
        _LOGGER.info("Main dashboard (None/'lovelace') not found, trying all %d dashboards", len(dashboards))
        for dash_name, dashboard_obj in dashboards.items():
            _LOGGER.info(
                "Trying dashboard '%s' (type=%s)",
                dash_name,
                type(dashboard_obj).__name__,
            )
            _LOGGER.debug("Dashboard object attributes: %s", dir(dashboard_obj))
            
            if hasattr(dashboard_obj, "config") and dashboard_obj.config is not None:
                config_obj = dashboard_obj.config
                if hasattr(config_obj, "async_load"):
                    current = await config_obj.async_load(False)
                    if isinstance(current, dict):
                        views = list(current.get("views", []))
                        views = [v for v in views if v.get("path") != "frigate-identity"]
                        views.append(view)
                        current["views"] = views
                        await config_obj.async_save(current)
                        _LOGGER.info(
                            "Frigate Identity dashboard view updated in dashboard '%s'",
                            dash_name,
                        )
                        return True
                else:
                    _LOGGER.warning("Config object missing async_load method")
            else:
                _LOGGER.warning("Dashboard '%s' missing config attribute", dash_name)
        
        _LOGGER.error(
            "Could not find a suitable lovelace dashboard to update. "
            "Lovelace may be in YAML mode, not properly initialized, or the API has changed in HA 2026. "
            "Check the logs above for details about available dashboards and their structure."
        )
        return False

    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Failed to push Frigate Identity dashboard view. "
            "This may indicate an API change in Home Assistant 2026."
        )
        return False
