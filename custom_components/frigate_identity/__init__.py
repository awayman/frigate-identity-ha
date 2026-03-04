"""Frigate Identity integration for Home Assistant.

Provides real-time person identification and location tracking via MQTT,
with automatic entity creation, blueprint deployment, and dashboard generation.
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import time as dt_time
from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt as mqtt_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_time_change

from .const import (
    ATTR_FRIGATE_IDENTITY_IS_CHILD,
    ATTR_FRIGATE_IDENTITY_SAFE_ZONES,
    CONF_AUTO_DASHBOARD,
    CONF_DASHBOARD_REFRESH_TIME,
    DEFAULT_AUTO_DASHBOARD,
    DEFAULT_DASHBOARD_REFRESH_TIME,
    DOMAIN,
    EVENT_PERSONS_UPDATED,
)
from .dashboard import async_generate_dashboard
from .person_registry import PersonData, PersonRegistry

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)

PLATFORMS = [
    Platform.SENSOR,
    Platform.CAMERA,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Frigate Identity integration (YAML not used — see config flow)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Frigate Identity from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    config = {**entry.data, **entry.options}

    # ── Person registry ─────────────────────────────────────────────────
    registry = PersonRegistry(hass)
    hass.data[DOMAIN]["registry"] = registry

    # Load person metadata from HA person entities
    await registry.async_load_persons_from_ha()

    # ── Blueprint auto-deploy ───────────────────────────────────────────
    await hass.async_add_executor_job(_deploy_blueprints, hass)

    # ── Forward platforms ───────────────────────────────────────────────
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Dashboard auto-generation ───────────────────────────────────────
    auto_dashboard = config.get(CONF_AUTO_DASHBOARD, DEFAULT_AUTO_DASHBOARD)

    if auto_dashboard:
        # Debounced regeneration on person changes
        _debounce_handle: dict[str, Any] = {"cancel": None}

        @callback
        def _schedule_dashboard_regen(*_args: Any) -> None:
            """Schedule a debounced dashboard regeneration."""
            if _debounce_handle["cancel"] is not None:
                _debounce_handle["cancel"]()

            @callback
            def _do_regen(_now: Any = None) -> None:
                hass.async_create_task(
                    async_generate_dashboard(hass, registry, config)
                )

            _debounce_handle["cancel"] = async_call_later(
                hass, 10, _do_regen
            )

        # Regen on person list changes
        entry.async_on_unload(
            hass.bus.async_listen(EVENT_PERSONS_UPDATED, _schedule_dashboard_regen)
        )

        # Regen on area changes
        entry.async_on_unload(
            hass.bus.async_listen(
                "area_registry_updated", _schedule_dashboard_regen
            )
        )

        # Daily refresh
        refresh_time_str = config.get(
            CONF_DASHBOARD_REFRESH_TIME, DEFAULT_DASHBOARD_REFRESH_TIME
        )
        try:
            h, m = map(int, refresh_time_str.split(":"))
            refresh_time = dt_time(h, m)
        except (ValueError, AttributeError):
            refresh_time = dt_time(3, 0)

        @callback
        def _daily_regen(_now: Any) -> None:
            hass.async_create_task(
                async_generate_dashboard(hass, registry, config)
            )

        entry.async_on_unload(
            async_track_time_change(
                hass, _daily_regen, hour=refresh_time.hour, minute=refresh_time.minute, second=0
            )
        )

        # Initial generation (after a short delay so entities are loaded)
        @callback
        def _initial_regen(_now: Any = None) -> None:
            hass.async_create_task(
                async_generate_dashboard(hass, registry, config)
            )

        entry.async_on_unload(
            async_call_later(hass, 15, _initial_regen)
        )

    # ── Service: regenerate_dashboard ───────────────────────────────────
    async def _handle_regen_service(call: ServiceCall) -> None:
        await async_generate_dashboard(hass, registry, config)

    hass.services.async_register(DOMAIN, "regenerate_dashboard", _handle_regen_service)

    # ── Service: get_registry_status ────────────────────────────────────
    async def _handle_get_registry_status(call: ServiceCall) -> None:
        """Log the current person registry status for debugging."""
        persons = registry.person_names
        _LOGGER.info("=== Frigate Identity Registry Status ===")
        _LOGGER.info("Total persons registered: %d", len(persons))
        if persons:
            _LOGGER.info("Persons: %s", ", ".join(persons))
            for name in persons:
                person = registry.get_person(name)
                if person:
                    _LOGGER.info(
                        "  - %s: camera=%s, is_child=%s, safe_zones=%s",
                        name, person.camera, person.is_child, person.safe_zones
                    )
        else:
            _LOGGER.warning("No persons registered! Dashboard cannot be generated.")
            _LOGGER.warning("Add persons to Home Assistant (Settings → People) or wait for MQTT discovery.")
        _LOGGER.info("Auto-dashboard enabled: %s", auto_dashboard)
        _LOGGER.info("========================================")

    hass.services.async_register(DOMAIN, "get_registry_status", _handle_get_registry_status)

    # ── Service: set_debug_mode ─────────────────────────────────────────
    async def _handle_set_debug_mode(call: ServiceCall) -> None:
        """Set debug mode for the frigate identity service."""
        import json
        enabled = call.data.get("enabled", False)

        try:
            payload = json.dumps({"enabled": enabled})
            await mqtt_component.async_publish(
                hass,
                "frigate_identity/debug/set",
                payload,
                qos=0,
                retain=False,
            )
            _LOGGER.info("Published debug mode command: enabled=%s", enabled)
        except Exception as e:
            _LOGGER.error("Failed to publish debug mode command: %s", e)

    hass.services.async_register(
        DOMAIN,
        "set_debug_mode",
        _handle_set_debug_mode,
        schema=vol.Schema(
            {vol.Required("enabled"): vol.Boolean()}
        ),
    )

    # ── Service: update_person_profile ──────────────────────────────────
    async def _apply_person_profile(
        person_name: str | None,
        safe_zones: list[str],
        is_child: bool | None,
    ) -> None:
        """Apply profile updates to registry and mirrored HA state."""
        if not person_name:
            _LOGGER.error("person_name is required")
            return

        person = registry._persons.get(person_name)
        if person is None:
            person = PersonData(person_name)
            registry._persons[person_name] = person

        person.safe_zones = list(safe_zones)
        if is_child is not None:
            person.is_child = bool(is_child)

        person_slug = person_name.lower().replace(" ", "_")
        person_entity_id = f"person.{person_slug}"
        person_state = hass.states.get(person_entity_id)
        if person_state:
            attrs = dict(person_state.attributes)
            attrs[ATTR_FRIGATE_IDENTITY_SAFE_ZONES] = list(safe_zones)
            if is_child is not None:
                attrs[ATTR_FRIGATE_IDENTITY_IS_CHILD] = bool(is_child)
            hass.states.async_set(person_entity_id, person_state.state, attrs)

        await registry._async_notify_listeners()
        _LOGGER.info(
            "Updated profile for %s: is_child=%s safe_zones=%s",
            person_name,
            person.is_child,
            safe_zones,
        )

    async def _handle_update_person_profile(call: ServiceCall) -> None:
        """Update child/adult profile and safe zones for a person."""
        await _apply_person_profile(
            person_name=call.data.get("person_name"),
            safe_zones=list(call.data.get("safe_zones", [])),
            is_child=call.data.get("is_child"),
        )

    # Backward-compatible alias
    async def _handle_update_child_safe_zones(call: ServiceCall) -> None:
        """Backward-compatible alias for updating safe zones only."""
        await _apply_person_profile(
            person_name=call.data.get("person_name"),
            safe_zones=list(call.data.get("safe_zones", [])),
            is_child=None,
        )

    hass.services.async_register(
        DOMAIN,
        "update_person_profile",
        _handle_update_person_profile,
        schema=vol.Schema(
            {
                vol.Required("person_name"): str,
                vol.Optional("is_child"): bool,
                vol.Optional("safe_zones", default=[]): vol.All(
                    cv.ensure_list, [str]
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "update_child_safe_zones",
        _handle_update_child_safe_zones,
        schema=vol.Schema(
            {
                vol.Required("person_name"): str,
                vol.Optional("safe_zones", default=[]): vol.All(
                    cv.ensure_list, [str]
                ),
            }
        ),
    )

    # ── Reload listener ─────────────────────────────────────────────────
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Frigate Identity integration set up successfully")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop("registry", None)
        hass.services.async_remove(DOMAIN, "regenerate_dashboard")
        hass.services.async_remove(DOMAIN, "get_registry_status")
        hass.services.async_remove(DOMAIN, "set_debug_mode")
        hass.services.async_remove(DOMAIN, "update_person_profile")
        hass.services.async_remove(DOMAIN, "update_child_safe_zones")
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


# ── Blueprint deployment ────────────────────────────────────────────────


def _deploy_blueprints(hass: HomeAssistant) -> None:
    """Copy blueprint YAML files to HA's blueprints directory.

    Only overwrites if the source file is newer than the destination.
    """
    src_dir = os.path.join(
        os.path.dirname(__file__),
        "blueprints", "automation", "frigate_identity",
    )
    dest_dir = hass.config.path("blueprints", "automation", "frigate_identity")

    if not os.path.isdir(src_dir):
        _LOGGER.debug("Blueprint source directory not found: %s", src_dir)
        return

    os.makedirs(dest_dir, exist_ok=True)
    copied = 0

    for filename in os.listdir(src_dir):
        if not filename.endswith(".yaml"):
            continue

        src_path = os.path.join(src_dir, filename)
        dest_path = os.path.join(dest_dir, filename)

        # Only overwrite if source is newer
        if os.path.exists(dest_path):
            src_mtime = os.path.getmtime(src_path)
            dest_mtime = os.path.getmtime(dest_path)
            if src_mtime <= dest_mtime:
                continue
            _LOGGER.info("Updating blueprint: %s", filename)
        else:
            _LOGGER.info("Installing blueprint: %s", filename)

        shutil.copy2(src_path, dest_path)
        copied += 1

    if copied:
        _LOGGER.info("Deployed %d blueprint(s) to %s", copied, dest_dir)
    else:
        _LOGGER.debug("All blueprints are up to date")
