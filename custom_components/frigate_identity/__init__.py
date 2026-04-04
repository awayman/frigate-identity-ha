"""Frigate Identity integration for Home Assistant.

Provides real-time person identification and location tracking via MQTT,
with automatic entity creation, blueprint deployment, and dashboard generation.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt as mqtt_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_time_change, async_track_time_interval

from .const import (
    ATTR_FRIGATE_IDENTITY_IS_CHILD,
    ATTR_FRIGATE_IDENTITY_SAFE_ZONES,
    CONF_AUTO_DASHBOARD,
    CONF_MQTT_TOPIC_PREFIX,
    CONF_DASHBOARD_REFRESH_TIME,
    DEFAULT_AUTO_DASHBOARD,
    DEFAULT_DASHBOARD_REFRESH_TIME,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DEFAULT_SERVICE_HEALTH_CHECK_INTERVAL,
    DOMAIN,
    EVENT_PERSONS_UPDATED,
    TOPIC_HEARTBEAT,
    TOPIC_FALSE_POSITIVE,
    TOPIC_FALSE_POSITIVE_ACK,
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

    # ── MQTT heartbeat subscription ─────────────────────────────────────
    heartbeat_topic = TOPIC_HEARTBEAT.format(
        prefix=config.get(CONF_MQTT_TOPIC_PREFIX, DEFAULT_MQTT_TOPIC_PREFIX)
    )

    @callback
    def _handle_heartbeat_message(_msg: Any) -> None:
        registry.async_update_heartbeat()

    entry.async_on_unload(
        await mqtt_component.async_subscribe(
            hass,
            heartbeat_topic,
            _handle_heartbeat_message,
        )
    )
    _LOGGER.info("Subscribed to identity heartbeat topic %s", heartbeat_topic)

    # ── Dashboard auto-generation ───────────────────────────────────────
    auto_dashboard = config.get(CONF_AUTO_DASHBOARD, DEFAULT_AUTO_DASHBOARD)
    _LOGGER.info("Auto-dashboard enabled: %s", auto_dashboard)

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
            _LOGGER.debug("Triggering initial dashboard generation (15s delayed)")
            hass.async_create_task(
                async_generate_dashboard(hass, registry, config)
            )

        entry.async_on_unload(
            async_call_later(hass, 15, _initial_regen)
        )

    # ── Periodic health check / diagnostics ────────────────────────────
    async def _publish_disconnected_diagnostics(health: dict[str, Any]) -> None:
        """Publish service-disconnected diagnostics for observability."""
        timestamp = datetime.now(timezone.utc).isoformat()
        heartbeat_age_seconds = health.get("last_heartbeat_age_seconds")

        hass.bus.async_fire(
            "frigate_identity.service_disconnected",
            {"timestamp": timestamp},
        )

        payload = json.dumps(
            {
                "timestamp": timestamp,
                "health": health,
                "heartbeat_age_seconds": heartbeat_age_seconds,
            },
            separators=(",", ":"),
        )

        await mqtt_component.async_publish(
            hass,
            "frigate_identity/debug/health",
            payload,
            qos=0,
            retain=False,
        )

    @callback
    def _health_check(_now: Any) -> None:
        try:
            health = registry.get_service_health()
            _LOGGER.debug("Service health check: %s", health)
            if health.get("is_connected", False):
                return

            _LOGGER.warning(
                "Service disconnected — restart suppressed (hotfix/remove-addon-restart)"
            )
            hass.async_create_task(_publish_disconnected_diagnostics(health))
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while processing service health check")

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            _health_check,
            timedelta(minutes=DEFAULT_SERVICE_HEALTH_CHECK_INTERVAL),
        )
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
        _LOGGER.debug("Auto-dashboard enabled: %s", auto_dashboard)
        _LOGGER.info("========================================")

    hass.services.async_register(DOMAIN, "get_registry_status", _handle_get_registry_status)

    # ── Service: set_debug_mode ─────────────────────────────────────────
    async def _handle_set_debug_mode(call: ServiceCall) -> None:
        """Set debug mode for the frigate identity service."""
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

    # ── Service: clear_embeddings ──────────────────────────────────────
    async def _handle_clear_embeddings(call: ServiceCall) -> None:
        """Request a full embedding-store clear in the identity service."""
        reason = call.data.get("reason", "")

        try:
            payload = json.dumps({"confirm": True, "reason": reason})
            await mqtt_component.async_publish(
                hass,
                "frigate_identity/embeddings/clear",
                payload,
                qos=0,
                retain=False,
            )
            _LOGGER.warning(
                "Published embedding clear command to service (reason=%s)",
                reason or "not provided",
            )
        except Exception as e:
            _LOGGER.error("Failed to publish embedding clear command: %s", e)

    hass.services.async_register(
        DOMAIN,
        "clear_embeddings",
        _handle_clear_embeddings,
        schema=vol.Schema(
            {vol.Optional("reason", default=""): vol.Coerce(str)}
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

    # ── Service: report_false_positive ─────────────────────────────────
    async def _handle_report_false_positive(call: ServiceCall) -> None:
        """Publish a false-positive feedback message to the identity service."""
        await _async_submit_false_positive(hass, registry, call.data["person_id"])

    hass.services.async_register(
        DOMAIN,
        "report_false_positive",
        _handle_report_false_positive,
        schema=vol.Schema({vol.Required("person_id"): str}),
    )

    # Subscribe to ACK topic and surface result to operator as a notification
    @callback
    def _handle_false_positive_ack(msg: Any) -> None:
        """Handle ACK from the identity service after processing a false positive."""
        try:
            ack = json.loads(msg.payload)
        except (json.JSONDecodeError, AttributeError):
            _LOGGER.warning("Received invalid false-positive ACK payload")
            return

        notif_title, notif_msg, notif_id = _false_positive_notification_from_ack(ack)

        hass.async_create_task(
            _notify_operator(hass, title=notif_title, message=notif_msg, notification_id=notif_id)
        )

    entry.async_on_unload(
        await mqtt_component.async_subscribe(
            hass,
            TOPIC_FALSE_POSITIVE_ACK,
            _handle_false_positive_ack,
        )
    )
    _LOGGER.info("Subscribed to false-positive ACK topic %s", TOPIC_FALSE_POSITIVE_ACK)

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
        hass.services.async_remove(DOMAIN, "clear_embeddings")
        hass.services.async_remove(DOMAIN, "update_person_profile")
        hass.services.async_remove(DOMAIN, "update_child_safe_zones")
        hass.services.async_remove(DOMAIN, "report_false_positive")
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


def _build_false_positive_payload(
    registry: PersonRegistry,
    person_id: str,
    submitted_at_ms: int,
) -> str:
    """Build the outgoing MQTT payload for a false-positive report."""
    person = registry.get_person(person_id)
    event_id: str | None = None
    camera: str | None = None
    if person is not None:
        event_id = person.event_id
        camera = person.camera

    return json.dumps(
        {
            "person_id": person_id,
            "event_id": event_id,
            "camera": camera,
            "submitted_at": submitted_at_ms,
        }
    )


async def _async_submit_false_positive(
    hass: HomeAssistant,
    registry: PersonRegistry,
    person_id: str,
) -> None:
    """Submit false-positive feedback to the identity service via MQTT."""
    payload = _build_false_positive_payload(
        registry,
        person_id,
        int(time.time() * 1000),
    )
    try:
        await mqtt_component.async_publish(
            hass,
            TOPIC_FALSE_POSITIVE,
            payload,
            qos=1,
            retain=False,
        )
        _LOGGER.info("Published false-positive feedback for %s", person_id)
    except Exception as exc:
        _LOGGER.error(
            "Failed to publish false-positive feedback for %s: %s",
            person_id,
            exc,
        )
        await _notify_operator(
            hass,
            title="False Positive: Submission Failed",
            message=f"Could not submit false positive for {person_id}. Check MQTT connectivity.",
            notification_id=f"fp_error_{person_id}",
        )


def _false_positive_notification_from_ack(ack: dict[str, Any]) -> tuple[str, str, str]:
    """Return (title, message, notification_id) for an ACK payload."""
    person_id = ack.get("person_id", "unknown")
    status = ack.get("status", "unknown")
    message = ack.get("message", "")
    removed = ack.get("embeddings_removed", 0)

    if status == "ok":
        return (
            f"False Positive Reported: {person_id}",
            message or f"Removed {removed} embedding(s) for {person_id}.",
            f"fp_ok_{person_id}",
        )

    return (
        f"False Positive Failed: {person_id}",
        message or f"Service could not process the false positive for {person_id}.",
        f"fp_error_{person_id}",
    )


async def _notify_operator(
    hass: HomeAssistant,
    *,
    title: str,
    message: str,
    notification_id: str,
) -> None:
    """Create a persistent notification visible to all HA operators."""
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": title,
            "message": message,
            "notification_id": notification_id,
        },
    )


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
