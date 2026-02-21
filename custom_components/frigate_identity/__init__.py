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

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_AUTO_DASHBOARD,
    CONF_DASHBOARD_REFRESH_TIME,
    CONF_PERSONS_FILE,
    DEFAULT_AUTO_DASHBOARD,
    DEFAULT_DASHBOARD_REFRESH_TIME,
    DOMAIN,
    EVENT_PERSONS_UPDATED,
)
from .dashboard import async_generate_dashboard
from .person_registry import PersonRegistry

_LOGGER = logging.getLogger(__name__)

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

    persons_file = config.get(CONF_PERSONS_FILE, "")
    if persons_file:
        await registry.async_load_persons_yaml(persons_file)

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

            _debounce_handle["cancel"] = hass.helpers.event.async_call_later(
                10, _do_regen
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
            hass.helpers.event.async_call_later(15, _initial_regen)
        )

    # ── Service: regenerate_dashboard ───────────────────────────────────
    async def _handle_regen_service(call: ServiceCall) -> None:
        await async_generate_dashboard(hass, registry, config)

    hass.services.async_register(DOMAIN, "regenerate_dashboard", _handle_regen_service)

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
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


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
