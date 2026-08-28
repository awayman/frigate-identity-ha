"""Meshtastic geofence service and tracker sensors for Frigate Identity.

Provides:
  - configure_tracker_geofence service — sends polygon geofence config to a
    Meshtastic tracker device via the official Meshtastic HA integration.
  - FrigateIdentityTrackerGeofenceStatusSensor — in_geofence / outside_geofence
  - FrigateIdentityTrackerBatterySensor          — battery percent
  - FrigateIdentityTrackerPositionSensor         — last known lat/lon
  - FrigateIdentityTrackerRelaySensor            — relay state

Tracker status messages arrive as Meshtastic direct messages from the device.
The integration listens to the ``meshtastic.message_received`` HA event fired
by the official Meshtastic integration and parses JSON payloads matching the
schema documented in the issue spec.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import PERCENTAGE
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MESHTASTIC_SERVICE_SEND = "meshtastic.send_direct_message"
MESHTASTIC_EVENT_MESSAGE = "meshtastic.message_received"

# Geofence config message version
GEOFENCE_CONFIG_VERSION = 1

# ── Polygon validation helpers ───────────────────────────────────────────────


def _validate_polygon(polygon: list[list[float]]) -> str | None:
    """Return an error string if the polygon is invalid, or None if valid.

    Rules:
    - At least 3 coordinate pairs
    - Each point is [lat, lon] with lat ∈ [-90, 90] and lon ∈ [-180, 180]
    - No two consecutive duplicate points
    - Basic self-intersection check (O(n²) segment crossing test)
    """
    if len(polygon) < 3:
        return "Polygon must have at least 3 coordinate pairs"

    for i, point in enumerate(polygon):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return f"Point {i} must be a [lat, lon] pair"
        lat, lon = point
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return f"Point {i} coordinates must be numeric"
        if not -90 <= lat <= 90:
            return f"Point {i} latitude {lat} out of range [-90, 90]"
        if not -180 <= lon <= 180:
            return f"Point {i} longitude {lon} out of range [-180, 180]"

    # Check for consecutive duplicate points
    for i in range(len(polygon)):
        a = polygon[i]
        b = polygon[(i + 1) % len(polygon)]
        if a[0] == b[0] and a[1] == b[1]:
            return f"Polygon has duplicate consecutive points at index {i}"

    # Basic self-intersection check using 2D line-segment crossing
    n = len(polygon)
    segments = [(polygon[i], polygon[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 2, n):
            # Skip adjacent segments (they share a vertex and are not a cross)
            if i == 0 and j == n - 1:
                continue
            if _segments_intersect(segments[i], segments[j]):
                return f"Polygon has self-intersecting edges at segments {i} and {j}"

    return None


def _cross(o: list[float], a: list[float], b: list[float]) -> float:
    """2-D cross product of vectors OA and OB."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(
    p: list[float], q: list[float], r: list[float]
) -> bool:
    """Return True if point q lies on segment PR."""
    return (
        min(p[0], r[0]) <= q[0] <= max(p[0], r[0])
        and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
    )


def _segments_intersect(
    seg1: tuple[list[float], list[float]],
    seg2: tuple[list[float], list[float]],
) -> bool:
    """Return True if segment seg1 and seg2 properly intersect."""
    p1, q1 = seg1
    p2, q2 = seg2

    d1 = _cross(p2, q2, p1)
    d2 = _cross(p2, q2, q1)
    d3 = _cross(p1, q1, p2)
    d4 = _cross(p1, q1, q2)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True

    # Collinear cases
    if d1 == 0 and _on_segment(p2, p1, q2):
        return True
    if d2 == 0 and _on_segment(p2, q1, q2):
        return True
    if d3 == 0 and _on_segment(p1, p2, q1):
        return True
    return bool(d4 == 0 and _on_segment(p1, q2, q1))


# ── Service schema ────────────────────────────────────────────────────────────

CONFIGURE_TRACKER_GEOFENCE_SCHEMA = vol.Schema(
    {
        vol.Required("tracker_id"): cv.string,
        vol.Required("person_name"): cv.string,
        vol.Required("polygon"): vol.All(
            list,
            vol.Length(min=3),
            [vol.All(list, vol.Length(min=2, max=2))],
        ),
        vol.Optional("relay_entity"): cv.entity_id,
        vol.Optional("enable_beeper", default=False): vol.Boolean(),
        vol.Optional("geofence_name", default=""): cv.string,
    }
)


# ── Service handler ───────────────────────────────────────────────────────────


async def async_handle_configure_tracker_geofence(
    hass: HomeAssistant,
    call: ServiceCall,
    tracker_registry: TrackerRegistry,
) -> None:
    """Handle the configure_tracker_geofence service call.

    Validates the polygon, builds the config payload, sends it to the
    Meshtastic tracker via the official HA integration, and fires a
    confirmation event.
    """
    tracker_id: str = call.data["tracker_id"]
    person_name: str = call.data["person_name"]
    polygon: list[list[float]] = call.data["polygon"]
    relay_entity: str | None = call.data.get("relay_entity")
    enable_beeper: bool = call.data.get("enable_beeper", False)
    geofence_name: str = call.data.get("geofence_name", "") or f"{person_name}_geofence"

    _LOGGER.debug(
        "configure_tracker_geofence called: tracker_id=%s person=%s points=%d",
        tracker_id,
        person_name,
        len(polygon),
    )

    # ── Validate polygon ─────────────────────────────────────────────────
    error = _validate_polygon(polygon)
    if error:
        _LOGGER.error(
            "Invalid polygon for tracker %s / person %s: %s",
            tracker_id,
            person_name,
            error,
        )
        hass.bus.async_fire(
            "frigate_identity.geofence_config_error",
            {
                "tracker_id": tracker_id,
                "person_name": person_name,
                "error": error,
            },
        )
        return

    # ── Build config payload ─────────────────────────────────────────────
    payload: dict[str, Any] = {
        "type": "geofence_config",
        "tracker_id": tracker_id,
        "person_name": person_name,
        "geofence_name": geofence_name,
        "polygon": polygon,
        "enable_beeper": enable_beeper,
        "version": GEOFENCE_CONFIG_VERSION,
    }

    # Resolve optional relay GPIO from HA entity state
    if relay_entity:
        relay_state = hass.states.get(relay_entity)
        if relay_state is None:
            _LOGGER.warning(
                "relay_entity %s not found in HA — relay_gpio omitted from payload",
                relay_entity,
            )
        else:
            # Store the entity id so the tracker can reference it;
            # actual GPIO pin must be configured on the device side.
            payload["relay_entity"] = relay_entity

    payload_json = json.dumps(payload)

    # ── Check message size (Meshtastic max ~230 bytes per packet) ────────
    if len(payload_json.encode()) > 200:
        _LOGGER.warning(
            "Geofence payload is %d bytes — Meshtastic packets are limited to ~230 bytes. "
            "Large polygons may be truncated on the device.",
            len(payload_json.encode()),
        )

    # ── Send via Meshtastic HA integration ───────────────────────────────
    _LOGGER.debug("Sending geofence config to tracker %s: %s", tracker_id, payload_json)

    try:
        await hass.services.async_call(
            "meshtastic",
            "send_direct_message",
            {
                "target": tracker_id,
                "message": payload_json,
            },
            blocking=True,
        )
        _LOGGER.info(
            "Geofence config sent to tracker %s for person %s",
            tracker_id,
            person_name,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error(
            "Failed to send geofence config to tracker %s: %s",
            tracker_id,
            exc,
        )
        hass.bus.async_fire(
            "frigate_identity.geofence_config_error",
            {
                "tracker_id": tracker_id,
                "person_name": person_name,
                "error": str(exc),
            },
        )
        return

    # ── Fire confirmation event ──────────────────────────────────────────
    hass.bus.async_fire(
        "frigate_identity.geofence_config_sent",
        {
            "tracker_id": tracker_id,
            "person_name": person_name,
            "geofence_name": geofence_name,
            "polygon_points": len(polygon),
            "enable_beeper": enable_beeper,
        },
    )

    # Register tracker → person mapping for status sensor routing
    tracker_registry.register(tracker_id, person_name)


# ── Tracker registry (in-memory mapping of tracker → person) ─────────────────


class TrackerRegistry:
    """Tracks the mapping between Meshtastic tracker IDs and person names."""

    def __init__(self) -> None:
        """Initialise the registry."""
        self._mapping: dict[str, str] = {}
        self._listeners: list[Any] = []

    def register(self, tracker_id: str, person_name: str) -> None:
        """Register or update a tracker → person mapping."""
        self._mapping[tracker_id] = person_name
        _LOGGER.debug("Registered tracker %s → person %s", tracker_id, person_name)
        for listener in list(self._listeners):
            try:
                listener(tracker_id, person_name)
            except Exception:
                _LOGGER.exception("Error in tracker registry listener")

    def get_person(self, tracker_id: str) -> str | None:
        """Return the person name for the given tracker ID, or None."""
        return self._mapping.get(tracker_id)

    def add_listener(self, listener: Any) -> None:
        """Add a registration-change listener."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Any) -> None:
        """Remove a registration-change listener."""
        self._listeners.discard(listener) if hasattr(self._listeners, "discard") else None
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    @property
    def tracker_ids(self) -> list[str]:
        """Return all registered tracker IDs."""
        return list(self._mapping.keys())


# ── Sensor setup helper ───────────────────────────────────────────────────────


async def async_setup_tracker_sensors(
    hass: HomeAssistant,
    tracker_registry: TrackerRegistry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up tracker status sensors and subscribe to Meshtastic status events.

    Called from sensor.py's async_setup_entry so the sensors live on the
    standard HA sensor platform.
    """
    # Track which (tracker_id, person_name) tuples we have already created sensors for
    tracked: set[str] = set()
    _pending_status: dict[str, dict[str, Any]] = {}

    def _create_sensors_for_tracker(tracker_id: str, person_name: str) -> None:
        """Create the four tracker sensors if not yet present."""
        if tracker_id in tracked:
            return
        tracked.add(tracker_id)

        geofence_sensor = FrigateIdentityTrackerGeofenceStatusSensor(
            tracker_id, person_name
        )
        battery_sensor = FrigateIdentityTrackerBatterySensor(tracker_id, person_name)
        position_sensor = FrigateIdentityTrackerPositionSensor(tracker_id, person_name)
        relay_sensor = FrigateIdentityTrackerRelaySensor(tracker_id, person_name)

        async_add_entities(
            [geofence_sensor, battery_sensor, position_sensor, relay_sensor]
        )

        # Replay any buffered status that arrived before sensors were created
        if tracker_id in _pending_status:
            status = _pending_status.pop(tracker_id)
            geofence_sensor.update_from_status(status)
            battery_sensor.update_from_status(status)
            position_sensor.update_from_status(status)
            relay_sensor.update_from_status(status)

        _LOGGER.debug(
            "Created tracker sensors for %s / %s", tracker_id, person_name
        )

    # Register listener for future tracker registrations
    tracker_registry.add_listener(_create_sensors_for_tracker)

    # Create sensors for already-registered trackers
    for tid in tracker_registry.tracker_ids:
        person = tracker_registry.get_person(tid)
        if person:
            _create_sensors_for_tracker(tid, person)

    # Sensor lookup for status dispatch
    _geofence_sensors: dict[str, FrigateIdentityTrackerGeofenceStatusSensor] = {}
    _battery_sensors: dict[str, FrigateIdentityTrackerBatterySensor] = {}
    _position_sensors: dict[str, FrigateIdentityTrackerPositionSensor] = {}
    _relay_sensors: dict[str, FrigateIdentityTrackerRelaySensor] = {}

    @callback
    def _on_meshtastic_message(event: Event) -> None:
        """Handle meshtastic.message_received events and update sensors."""
        event_data = event.data or {}
        raw_message = event_data.get("message", "")
        sender = event_data.get("sender") or event_data.get("from", "")

        # Only process messages that look like JSON tracker status
        if not raw_message or not raw_message.strip().startswith("{"):
            return

        try:
            status: dict[str, Any] = json.loads(raw_message)
        except (json.JSONDecodeError, ValueError):
            return

        # Identify which tracker sent the message.
        # The official Meshtastic integration typically exposes the device ID
        # in event_data["sender"] or "from".  We also accept a "device" field
        # inside the payload (as specified in the issue schema).
        tracker_id: str | None = (
            str(sender)
            if sender
            else status.get("device", "").replace("Tracker-", "").strip() or None
        )

        if not tracker_id:
            _LOGGER.debug(
                "Received Meshtastic status with no identifiable tracker ID: %s",
                raw_message[:200],
            )
            return

        person_name = tracker_registry.get_person(tracker_id)
        if person_name is None:
            # Buffer the status in case sensors are created imminently
            _pending_status[tracker_id] = status
            _LOGGER.debug(
                "Received status for unregistered tracker %s — buffered", tracker_id
            )
            return

        # Dispatch to sensors
        if tracker_id in _geofence_sensors:
            _geofence_sensors[tracker_id].update_from_status(status)
        if tracker_id in _battery_sensors:
            _battery_sensors[tracker_id].update_from_status(status)
        if tracker_id in _position_sensors:
            _position_sensors[tracker_id].update_from_status(status)
        if tracker_id in _relay_sensors:
            _relay_sensors[tracker_id].update_from_status(status)

        # Fire geofence transition events
        geofence_status = status.get("status", "")
        if geofence_status == "outside_geofence":
            hass.bus.async_fire(
                "frigate_identity.tracker_geofence_violation",
                {
                    "tracker_id": tracker_id,
                    "person_name": person_name,
                    "latitude": status.get("latitude"),
                    "longitude": status.get("longitude"),
                },
            )
        elif geofence_status == "in_geofence":
            hass.bus.async_fire(
                "frigate_identity.tracker_geofence_entry",
                {
                    "tracker_id": tracker_id,
                    "person_name": person_name,
                    "latitude": status.get("latitude"),
                    "longitude": status.get("longitude"),
                },
            )

    hass.bus.async_listen(MESHTASTIC_EVENT_MESSAGE, _on_meshtastic_message)


# ── Sensor implementations ────────────────────────────────────────────────────


class _TrackerSensorBase(SensorEntity):
    """Base class for Meshtastic tracker status sensors."""

    _attr_has_entity_name = True

    def __init__(self, tracker_id: str, person_name: str, suffix: str) -> None:
        """Initialise the sensor."""
        self._tracker_id = tracker_id
        self._person_name = person_name
        slug = person_name.lower().replace(" ", "_").replace("-", "_")
        tid_slug = tracker_id.lower().replace("-", "_").replace(" ", "_")
        self._attr_name = f"{person_name} {suffix}"
        self._attr_unique_id = f"frigate_identity_{slug}_tracker_{tid_slug}_{suffix.lower().replace(' ', '_')}"
        self._attr_extra_state_attributes: dict[str, Any] = {
            "tracker_id": tracker_id,
        }

    def update_from_status(self, status: dict[str, Any]) -> None:
        """Update sensor state from a received tracker status payload."""
        raise NotImplementedError


class FrigateIdentityTrackerGeofenceStatusSensor(_TrackerSensorBase):
    """Reports whether the tracker is inside or outside the geofence."""

    def __init__(self, tracker_id: str, person_name: str) -> None:
        """Initialise the sensor."""
        super().__init__(tracker_id, person_name, "Geofence Status")
        self._attr_native_value: str = "unknown"

    def update_from_status(self, status: dict[str, Any]) -> None:
        """Update from tracker status payload."""
        geofence_status = status.get("status")
        if geofence_status in ("in_geofence", "outside_geofence"):
            self._attr_native_value = geofence_status
        self._attr_extra_state_attributes = {
            "tracker_id": self._tracker_id,
            "gps_fix": status.get("gps_fix"),
            "timestamp": status.get("timestamp"),
        }
        self.async_write_ha_state()


class FrigateIdentityTrackerBatterySensor(_TrackerSensorBase):
    """Reports tracker battery percentage."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, tracker_id: str, person_name: str) -> None:
        """Initialise the sensor."""
        super().__init__(tracker_id, person_name, "Battery")
        self._attr_native_value: int | None = None

    def update_from_status(self, status: dict[str, Any]) -> None:
        """Update from tracker status payload."""
        battery = status.get("battery_percent")
        if isinstance(battery, (int, float)):
            self._attr_native_value = int(battery)
        self._attr_extra_state_attributes = {
            "tracker_id": self._tracker_id,
            "timestamp": status.get("timestamp"),
        }
        self.async_write_ha_state()


class FrigateIdentityTrackerPositionSensor(_TrackerSensorBase):
    """Reports the last known GPS position as a 'lat,lon' string."""

    def __init__(self, tracker_id: str, person_name: str) -> None:
        """Initialise the sensor."""
        super().__init__(tracker_id, person_name, "Last Position")
        self._attr_native_value: str | None = None

    def update_from_status(self, status: dict[str, Any]) -> None:
        """Update from tracker status payload."""
        lat = status.get("latitude")
        lon = status.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            self._attr_native_value = f"{lat},{lon}"
        self._attr_extra_state_attributes = {
            "tracker_id": self._tracker_id,
            "latitude": lat,
            "longitude": lon,
            "gps_fix": status.get("gps_fix"),
            "timestamp": status.get("timestamp"),
        }
        self.async_write_ha_state()


class FrigateIdentityTrackerRelaySensor(_TrackerSensorBase):
    """Reports the relay state reported by the tracker."""

    def __init__(self, tracker_id: str, person_name: str) -> None:
        """Initialise the sensor."""
        super().__init__(tracker_id, person_name, "Relay State")
        self._attr_native_value: str | None = None

    def update_from_status(self, status: dict[str, Any]) -> None:
        """Update from tracker status payload."""
        relay_enabled = status.get("relay_enabled")
        if relay_enabled is True:
            self._attr_native_value = "enabled"
        elif relay_enabled is False:
            self._attr_native_value = "disabled"
        self._attr_extra_state_attributes = {
            "tracker_id": self._tracker_id,
            "relay_enabled": relay_enabled,
            "timestamp": status.get("timestamp"),
        }
        self.async_write_ha_state()
