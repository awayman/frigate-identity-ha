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
    CONF_PERSON_ORDER,
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


# ── Sort key ────────────────────────────────────────────────────────────


def _person_sort_key(
    person_name: str,
    person_order_map: dict[str, int],
    registry: PersonRegistry,
) -> tuple:
    """Return sort tuple: (bucket, order, name_lower).

    Bucket 0 = explicit entry.options order, 1 = YAML meta order, 2 = alpha.
    """
    explicit = person_order_map.get(person_name)
    if explicit is not None:
        return (0, explicit, person_name.lower())
    meta_order = registry.meta.get(person_name, {}).get("order")
    if meta_order is not None:
        try:
            return (1, int(meta_order), person_name.lower())
        except (ValueError, TypeError):
            pass
    return (2, 0, person_name.lower())


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


def _person_header_card(person: str, location_entity: str) -> dict[str, Any]:
    """Build a markdown header card showing person name and relative last-seen time."""
    content = (
        f"<h2>{person}</h2>\n"
        f"Last seen: <ha-relative-time "
        f"datetime=\"{{{{ state_attr('{location_entity}', 'last_seen') or "
        f"states['{location_entity}'].last_changed }}}}\""
        f"></ha-relative-time>"
    )
    return {"type": "markdown", "content": content}


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

    header_card = _person_header_card(person, location_entity)

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

    return {
        "type": "vertical-stack",
        "cards": [header_card, snapshot_card, status_card, _false_positive_button(person)],
    }


# ── View builder ────────────────────────────────────────────────────────


def _build_view(
    hass: HomeAssistant,
    persons: list[str],
    snapshot_source: str,
    registry: PersonRegistry,
    dashboard_name: str,
) -> dict[str, Any]:
    """Build a complete Lovelace view dict (flat per-person cards, no area grouping)."""
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

    person_cards = [
        _person_card(hass, p, snapshot_source, registry) for p in persons
    ]

    return {
        "title": dashboard_name,
        "path": "frigate-identity",
        "icon": "mdi:account-search",
        "cards": [banner_card, header_card, *person_cards, summary_card],
    }


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

    # ── Step 1: collect persons ─────────────────────────────────────────
    filter_persons = config.get(CONF_DASHBOARD_PERSONS, DEFAULT_DASHBOARD_PERSONS)
    if filter_persons:
        persons: list[str] = [p for p in registry.person_names if p in filter_persons]
        _LOGGER.debug(
            "Collect: person filter applied — %d selected, %d matched in registry",
            len(filter_persons),
            len(persons),
        )
    else:
        persons = list(registry.person_names)
        _LOGGER.debug("Collect: no person filter — %d persons from registry", len(persons))

    # ── Step 2: filter unknown persons ─────────────────────────────────
    before = len(persons)
    persons = [p for p in persons if not p.lower().startswith("unknown")]
    _LOGGER.debug(
        "Filter: removed %d unknown persons → %d remaining",
        before - len(persons),
        len(persons),
    )

    if not persons:
        _LOGGER.warning("No persons to display on dashboard; skipping generation")
        return False

    # ── Step 3: sort persons ────────────────────────────────────────────
    person_order_map: dict[str, int] = config.get(CONF_PERSON_ORDER, {}) or {}
    persons = sorted(
        persons,
        key=lambda p: _person_sort_key(p, person_order_map, registry),
    )
    _LOGGER.debug("Sort: person_order_map=%s → sorted=%s", person_order_map, persons)

    # ── Step 4: build view ──────────────────────────────────────────────
    snapshot_source = config.get(CONF_SNAPSHOT_SOURCE, DEFAULT_SNAPSHOT_SOURCE)
    dashboard_name = str(
        config.get(CONF_DASHBOARD_NAME, DEFAULT_DASHBOARD_NAME)
    ).strip() or DEFAULT_DASHBOARD_NAME
    _LOGGER.debug("Build: snapshot_source=%s, dashboard_name=%s", snapshot_source, dashboard_name)

    view = _build_view(hass, persons, snapshot_source, registry, dashboard_name)
    _LOGGER.debug("Build: view built with %d cards", len(view.get("cards", [])))

    # ── Step 5: push to Lovelace ────────────────────────────────────────
    _LOGGER.debug(
        "Push: lovelace_available=%s, persons=%d, snapshot_source=%s",
        "lovelace" in hass.data,
        len(persons),
        snapshot_source,
    )
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


