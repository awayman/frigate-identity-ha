"""Dashboard generation for Frigate Identity.

Builds a Lovelace view and pushes it to HA's storage-mode dashboard.
Automatically creates and maintains a dedicated dashboard for person tracking.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import ConfigNotFound
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er

from .const import (
    CONF_DASHBOARD_NAME,
    CONF_DASHBOARD_PERSONS,
    CONF_SNAPSHOT_SOURCE,
    DEFAULT_DASHBOARD_NAME,
    DEFAULT_DASHBOARD_PERSONS,
    DEFAULT_SNAPSHOT_SOURCE,
    DOMAIN,
    SNAPSHOT_SOURCE_FRIGATE_API,
    SNAPSHOT_SOURCE_MQTT,
)
from .person_registry import PersonRegistry

_LOGGER = logging.getLogger(__name__)


def _slug(name: str) -> str:
    """Return a lowercase underscore slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


def _false_positive_button(person: str) -> dict[str, Any]:
    """Build a 'Report False Positive' button card for a person."""
    return {
        "type": "button",
        "name": "Report False Positive",
        "icon": "mdi:thumb-down-outline",
        "tap_action": {
            "action": "call-service",
            "service": f"{DOMAIN}.report_false_positive",
            "service_data": {"person_id": person},
        },
    }


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


def _resolve_entity_id(
    hass: HomeAssistant,
    *,
    domain: str,
    unique_id: str,
    candidates: list[str],
) -> str:
    """Resolve an entity ID via entity registry, then state/candidate fallbacks."""
    try:
        ent_reg = er.async_get(hass)
        resolved = ent_reg.async_get_entity_id(domain, DOMAIN, unique_id)
        if resolved:
            return resolved
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Unable to resolve %s/%s via entity registry", domain, unique_id)

    for candidate in candidates:
        if hass.states.get(candidate) is not None:
            return candidate

    return candidates[0]


def _person_card(
    hass: HomeAssistant,
    person: str,
    snapshot_source: str,
    registry: PersonRegistry,
) -> dict[str, Any]:
    """Build a vertical-stack card for one person."""
    slug = _slug(person)
    location_entity = _resolve_entity_id(
        hass,
        domain="sensor",
        unique_id=f"frigate_identity_{slug}_location",
        candidates=[
            f"sensor.frigate_identity_{slug}_location",
            f"sensor.{slug}_location",
        ],
    )

    if snapshot_source == SNAPSHOT_SOURCE_MQTT:
        snap_entity = _resolve_entity_id(
            hass,
            domain="camera",
            unique_id=f"frigate_identity_{slug}_snapshot",
            candidates=[
                f"camera.frigate_identity_{slug}_snapshot",
                f"camera.{slug}_snapshot",
            ],
        )
    else:
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
        supervised_entity = _resolve_entity_id(
            hass,
            domain="binary_sensor",
            unique_id=f"frigate_identity_{slug}_supervised",
            candidates=[
                f"binary_sensor.frigate_identity_{slug}_supervised",
                f"binary_sensor.{slug}_supervised",
            ],
        )
        status_entities.insert(
            1,
            {
                "entity": supervised_entity,
                "name": "Supervised",
            },
        )

    status_card: dict[str, Any] = {
        "type": "entities",
        "title": f"{person} Status",
        "entities": status_entities,
    }

    return {"type": "vertical-stack", "cards": [snapshot_card, status_card, _false_positive_button(person)]}


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
    hass: HomeAssistant,
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
        _person_card(hass, p, snapshot_source, registry) for p in persons_in_area
    ]
    if len(person_cards) > 1:
        cards.append({"type": "horizontal-stack", "cards": person_cards})
    elif person_cards:
        cards.append(person_cards[0])

    return cards


# ── View builder ────────────────────────────────────────────────────────


def _build_view(
    hass: HomeAssistant,
    persons: list[str],
    snapshot_source: str,
    registry: PersonRegistry,
    dashboard_name: str,
    area_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a complete Lovelace view dict."""
    service_status_entity = _resolve_entity_id(
        hass,
        domain="binary_sensor",
        unique_id="frigate_identity_service_status",
        candidates=["binary_sensor.frigate_identity_service_status"],
    )
    banner_card: dict[str, Any] = {
        "type": "conditional",
        "conditions": [
            {"entity": service_status_entity, "state_not": "on"},
        ],
        "card": {
            "type": "markdown",
            "content": (
                "## Identity Service Offline\n"
                "No recent heartbeat was received from the identity service. "
                "Displayed person data may be stale until the service reconnects."
            ),
        },
    }
    header_card: dict[str, Any] = {
        "type": "markdown",
        "content": (
            f"# 📍 {dashboard_name} – Person Tracker\n"
            "Real-time location and bounded snapshot for each tracked person."
        ),
    }
    summary_card: dict[str, Any] = {
        "type": "entities",
        "title": "System Status",
        "entities": [
            {"entity": service_status_entity, "name": "Identity Service"},
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
                _area_section(hass, area, ppl, snapshot_source, registry)
            )

        unassigned = [p for p in persons if not person_area[p]]
        if unassigned:
            body_cards.extend(
                _area_section(hass, "Unassigned", unassigned, snapshot_source, registry)
            )
    else:
        body_cards = [
            _person_card(hass, p, snapshot_source, registry) for p in persons
        ]

    return {
        "title": dashboard_name,
        "path": "frigate-identity",
        "icon": "mdi:account-search",
        "cards": [banner_card, header_card, *body_cards, summary_card],
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
    
    # Apply person filter if configured
    filter_persons = config.get(CONF_DASHBOARD_PERSONS, DEFAULT_DASHBOARD_PERSONS)
    if filter_persons:
        # Non-empty list: show only selected persons that exist in registry
        persons = [p for p in registry.person_names if p in filter_persons]
        _LOGGER.debug(
            "Applying person filter: %d selected, %d matched in registry",
            len(filter_persons),
            len(persons),
        )
    else:
        # Empty list (default): show all persons including new discoveries
        persons = registry.person_names
        _LOGGER.debug("No person filter applied; showing all persons")
    
    _LOGGER.debug("Persons for dashboard: %d - %s", len(persons), persons)
    
    if not persons:
        _LOGGER.warning("No persons to display on dashboard; skipping generation")
        if filter_persons:
            _LOGGER.warning(
                "Filter specified %d persons but none exist in registry",
                len(filter_persons),
            )
        else:
            _LOGGER.warning("Dashboard cannot be created without persons!")
        return False

    snapshot_source = config.get(CONF_SNAPSHOT_SOURCE, DEFAULT_SNAPSHOT_SOURCE)
    dashboard_name = str(
        config.get(CONF_DASHBOARD_NAME, DEFAULT_DASHBOARD_NAME)
    ).strip() or DEFAULT_DASHBOARD_NAME
    _LOGGER.debug("Snapshot source: %s", snapshot_source)

    # Merge camera_zones overrides with HA area assignments
    ha_areas = await _fetch_area_map(hass)
    area_map = {**ha_areas, **registry.camera_zones}
    _LOGGER.debug("Area map loaded: %d areas", len(area_map) if area_map else 0)

    view = _build_view(
        hass,
        persons,
        snapshot_source,
        registry,
        dashboard_name,
        area_map or None,
    )
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
        lovelace_data = hass.data.get("lovelace")
        if not lovelace_data or not hasattr(lovelace_data, "dashboards"):
            _LOGGER.error("Lovelace dashboards API unavailable; cannot generate sidebar dashboard")
            return False

        dashboards_obj = lovelace_data.dashboards
        target_url_path = "frigate-identity"
        target_dashboard = dashboards_obj.get(target_url_path)

        if target_dashboard is None:
            from homeassistant.components.lovelace.dashboard import LovelaceStorage

            dashboard_config = {
                "id": target_url_path,
                "url_path": target_url_path,
                "title": dashboard_name,
                "icon": "mdi:account-search",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            }
            target_dashboard = LovelaceStorage(hass, dashboard_config)
            dashboards_obj[target_url_path] = target_dashboard
            _LOGGER.info("Created dedicated '%s' Lovelace dashboard object", target_url_path)
        elif getattr(target_dashboard, "config", None):
            target_dashboard.config["title"] = dashboard_name
            target_dashboard.config["icon"] = "mdi:account-search"
            target_dashboard.config["show_in_sidebar"] = True
            target_dashboard.config["require_admin"] = False

        try:
            current = await target_dashboard.async_load(False)
        except ConfigNotFound:
            current = {"views": []}

        if not isinstance(current, dict):
            current = {"views": []}

        views = list(current.get("views", []))
        views = [v for v in views if v.get("path") != "frigate-identity"]
        views.append(view)
        current["views"] = views
        await target_dashboard.async_save(current)

        # Register/update dedicated sidebar panel so the dashboard name appears in sidebar.
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            frontend_url_path=target_url_path,
            require_admin=False,
            show_in_sidebar=True,
            sidebar_title=dashboard_name,
            sidebar_icon="mdi:account-search",
            config={"mode": "storage"},
            update=True,
        )

        # Remove any old Frigate Identity tab from default dashboards.
        for default_key in (None, "lovelace"):
            default_dash = dashboards_obj.get(default_key)
            if not default_dash or default_dash is target_dashboard:
                continue
            if not hasattr(default_dash, "async_load") or not hasattr(default_dash, "async_save"):
                continue
            try:
                default_config = await default_dash.async_load(False)
            except ConfigNotFound:
                continue

            if not isinstance(default_config, dict):
                continue
            default_views = list(default_config.get("views", []))
            filtered_views = [v for v in default_views if v.get("path") != "frigate-identity"]
            if len(filtered_views) != len(default_views):
                default_config["views"] = filtered_views
                await default_dash.async_save(default_config)

        _LOGGER.info("✅ Sidebar dashboard '%s' updated with title '%s'", target_url_path, dashboard_name)
        return True

    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Failed to push Frigate Identity dashboard view. "
            "This may indicate an API change in Home Assistant 2026."
        )
        return False
