"""Meshtastic geofence service and tracker sensors for Frigate Identity."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

try:
    import homeassistant.helpers.config_validation as cv
except ImportError:  # pragma: no cover - test stubs
    class _ConfigValidation:
        string = str
        entity_id = str

    cv = _ConfigValidation()

if not hasattr(cv, "string"):  # pragma: no cover - test stubs
    cv.string = str
if not hasattr(cv, "entity_id"):  # pragma: no cover - test stubs
    cv.entity_id = str

try:
    import voluptuous as vol
except ImportError:  # pragma: no cover - test stubs
    class _Voluptuous:
        @staticmethod
        def Schema(*_args: Any, **_kwargs: Any) -> Callable[[Any], Any]:
            return lambda value: value

        @staticmethod
        def Required(name: str) -> str:
            return name

        @staticmethod
        def Optional(name: str, default: Any = None) -> str:
            return name

        @staticmethod
        def All(*_args: Any) -> type[list]:
            return list

        @staticmethod
        def Length(*_args: Any, **_kwargs: Any) -> type[list]:
            return list

        @staticmethod
        def Boolean() -> type[bool]:
            return bool

        @staticmethod
        def Coerce(value_type: Any) -> Any:
            return value_type

    vol = _Voluptuous()

for _name, _fallback in {  # pragma: no cover - test stubs
    "Schema": lambda *_args, **_kwargs: (lambda value: value),
    "Required": lambda name: name,
    "Optional": lambda name, default=None: name,
    "All": lambda *_args: list,
    "Length": lambda *_args, **_kwargs: list,
    "Boolean": lambda: bool,
    "Coerce": lambda value_type: value_type,
}.items():
    if not hasattr(vol, _name):
        setattr(vol, _name, staticmethod(_fallback))

try:
    from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
except ImportError:  # pragma: no cover - test stubs
    class SensorEntity:
        """Fallback sensor base for test stubs."""

        def async_write_ha_state(self) -> None:
            return

    class SensorDeviceClass:
        """Fallback sensor device classes for test stubs."""

        BATTERY = "battery"
        TIMESTAMP = "timestamp"

try:
    from homeassistant.const import PERCENTAGE
except ImportError:  # pragma: no cover - test stubs
    PERCENTAGE = "%"

try:
    from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
except ImportError:  # pragma: no cover - test stubs
    Event = HomeAssistant = ServiceCall = object

    def callback(func: Callable[..., Any]) -> Callable[..., Any]:
        return func

try:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:  # pragma: no cover - test stubs
    AddEntitiesCallback = object

try:
    from homeassistant.exceptions import HomeAssistantError
except ImportError:  # pragma: no cover - test stubs
    class HomeAssistantError(RuntimeError):
        """Fallback Home Assistant error used by test stubs."""


try:
    from homeassistant.helpers.storage import Store
except ImportError:  # pragma: no cover - test stubs
    Store = None

_LOGGER = logging.getLogger(__name__)

MESHTASTIC_DOMAIN = "meshtastic"
MESHTASTIC_SERVICE_SEND = "send_direct_message"
MESHTASTIC_EVENT_MESSAGE = "meshtastic.message_received"

GEOFENCE_CONFIG_VERSION = 1
STORAGE_VERSION = 1
STORAGE_KEY = "frigate_identity_meshtastic_geofences"
MAX_DIRECT_MESSAGE_BYTES = 240
LOW_BATTERY_THRESHOLD = 10
MAX_SEND_ATTEMPTS = 3

DEFAULT_ENABLE_BEEPER = True
DEFAULT_BUZZER_GPIO = 0
DEFAULT_WARN_DIST_APPROACHING = 50
DEFAULT_WARN_DIST_NEAR = 20
DEFAULT_WARN_DIST_CRITICAL = 5

_TIMESTAMP_DEVICE_CLASS = getattr(SensorDeviceClass, "TIMESTAMP", None)


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return the 2-D cross product for three points."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(
    p: tuple[float, float],
    q: tuple[float, float],
    r: tuple[float, float],
) -> bool:
    """Return True when q lies on segment PR."""
    return (
        min(p[0], r[0]) <= q[0] <= max(p[0], r[0])
        and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
    )


def _segments_intersect(
    seg1: tuple[tuple[float, float], tuple[float, float]],
    seg2: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    """Return True when two segments intersect."""
    p1, q1 = seg1
    p2, q2 = seg2

    d1 = _cross(p2, q2, p1)
    d2 = _cross(p2, q2, q1)
    d3 = _cross(p1, q1, p2)
    d4 = _cross(p1, q1, q2)

    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True

    if d1 == 0 and _on_segment(p2, p1, q2):
        return True
    if d2 == 0 and _on_segment(p2, q1, q2):
        return True
    if d3 == 0 and _on_segment(p1, p2, q1):
        return True
    return bool(d4 == 0 and _on_segment(p1, q2, q1))


def _normalize_polygon(raw_polygon: list[Any]) -> list[list[float]]:
    """Normalize the polygon into a JSON-serializable float coordinate list."""
    polygon: list[list[float]] = []
    for point in raw_polygon:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise HomeAssistantError("Polygon points must be [latitude, longitude] pairs")
        polygon.append([float(point[0]), float(point[1])])
    return polygon


def _validate_polygon(polygon: list[list[float]]) -> str | None:
    """Return a validation error string, or None when the polygon is valid."""
    if len(polygon) < 3:
        return "Polygon must have at least 3 points"

    normalized = [(point[0], point[1]) for point in polygon]
    for lat, lon in normalized:
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            return "Latitude must be -90 to 90, longitude -180 to 180"

    segment_count = len(normalized)
    for index in range(segment_count):
        if normalized[index] == normalized[(index + 1) % segment_count]:
            return "Polygon is self-intersecting"

    segments = [
        (normalized[index], normalized[(index + 1) % segment_count])
        for index in range(segment_count)
    ]
    for left_index in range(segment_count):
        for right_index in range(left_index + 2, segment_count):
            if left_index == 0 and right_index == segment_count - 1:
                continue
            if _segments_intersect(segments[left_index], segments[right_index]):
                return "Polygon is self-intersecting"

    return None


def _extract_relay_gpio(hass: HomeAssistant, relay_entity: str | None) -> int | None:
    """Extract a tracker relay GPIO hint from an HA switch entity, if present."""
    if not relay_entity or not hasattr(hass, "states"):
        return None

    relay_state = hass.states.get(relay_entity)
    if relay_state is None:
        _LOGGER.debug("Relay entity %s was not found in Home Assistant", relay_entity)
        return None

    attributes = getattr(relay_state, "attributes", {}) or {}
    for key in ("relay_gpio", "gpio_pin", "gpio", "pin"):
        value = attributes.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)

    _LOGGER.debug("Relay entity %s has no GPIO metadata; omitting relay_gpio", relay_entity)
    return None


def _build_geofence_config(
    hass: HomeAssistant,
    call: ServiceCall,
    polygon: list[list[float]],
) -> dict[str, Any]:
    """Build the persisted geofence configuration from a service call."""
    geofence_name = call.data.get("geofence_name")
    relay_entity = call.data.get("relay_entity")
    config: dict[str, Any] = {
        "tracker_id": str(call.data["tracker_id"]),
        "person_name": str(call.data["person_name"]),
        "geofence_name": str(geofence_name) if geofence_name else "",
        "polygon": polygon,
        "relay_entity": relay_entity,
        "relay_gpio": _extract_relay_gpio(hass, relay_entity),
        "enable_beeper": bool(call.data.get("enable_beeper", DEFAULT_ENABLE_BEEPER)),
        "buzzer_gpio": int(call.data.get("buzzer_gpio", DEFAULT_BUZZER_GPIO)),
        "warn_dist_approaching": int(
            call.data.get("warn_dist_approaching", DEFAULT_WARN_DIST_APPROACHING)
        ),
        "warn_dist_near": int(call.data.get("warn_dist_near", DEFAULT_WARN_DIST_NEAR)),
        "warn_dist_critical": int(
            call.data.get("warn_dist_critical", DEFAULT_WARN_DIST_CRITICAL)
        ),
        "version": GEOFENCE_CONFIG_VERSION,
    }
    return config


def _build_tracker_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Build the compact payload sent to the Meshtastic tracker."""
    payload: dict[str, Any] = {
        "type": "geofence_config",
        "tracker_id": config["tracker_id"],
        "person_name": config["person_name"],
        "polygon": config["polygon"],
        "enable_beeper": config["enable_beeper"],
        "version": config["version"],
    }

    geofence_name = config.get("geofence_name")
    if geofence_name:
        payload["geofence_name"] = geofence_name

    relay_gpio = config.get("relay_gpio")
    if relay_gpio is not None:
        payload["relay_gpio"] = relay_gpio

    buzzer_gpio = config.get("buzzer_gpio", DEFAULT_BUZZER_GPIO)
    if buzzer_gpio != DEFAULT_BUZZER_GPIO:
        payload["buzzer_gpio"] = buzzer_gpio

    for key, default in (
        ("warn_dist_approaching", DEFAULT_WARN_DIST_APPROACHING),
        ("warn_dist_near", DEFAULT_WARN_DIST_NEAR),
        ("warn_dist_critical", DEFAULT_WARN_DIST_CRITICAL),
    ):
        if config.get(key) != default:
            payload[key] = config[key]

    return payload


def _encode_payload(payload: dict[str, Any]) -> str:
    """Encode a tracker payload as compact JSON."""
    return json.dumps(payload, separators=(",", ":"))


def _message_size_error(payload_json: str) -> str:
    """Return a user-facing size-limit error."""
    return (
        "Geofence payload exceeds the Meshtastic direct-message size limit "
        f"({len(payload_json.encode())}/{MAX_DIRECT_MESSAGE_BYTES} bytes); "
        "simplify the polygon or omit optional fields"
    )


def _coerce_timestamp(value: Any) -> str | None:
    """Convert tracker timestamps to ISO-8601 strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).isoformat()
        except ValueError:
            return value
    return str(value)


def _status_candidates(raw_value: Any) -> list[dict[str, Any]]:
    """Expand raw status event data into possible tracker-status dictionaries."""
    candidates: list[dict[str, Any]] = []
    queue = [raw_value]
    while queue:
        current = queue.pop(0)
        if isinstance(current, str):
            current = current.strip()
            if not current.startswith("{"):
                continue
            try:
                parsed = json.loads(current)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            queue.append(parsed)
            continue

        if isinstance(current, dict):
            if "status" in current and ("device" in current or "tracker_id" in current):
                candidates.append(current)
            for key in ("message", "payload", "decoded", "text"):
                nested = current.get(key)
                if nested is not None:
                    queue.append(nested)

    return candidates


def _extract_tracker_id(event_data: dict[str, Any], status: dict[str, Any]) -> str | None:
    """Extract the tracker ID from Meshtastic event data."""
    for key in ("sender", "from", "from_id", "tracker_id", "device"):
        value = event_data.get(key)
        if value:
            tracker_id = str(value).replace("Tracker-", "").strip()
            if tracker_id:
                return tracker_id

    for key in ("tracker_id", "device"):
        value = status.get(key)
        if value:
            tracker_id = str(value).replace("Tracker-", "").strip()
            if tracker_id:
                return tracker_id

    return None


class TrackerRegistry:
    """Track Meshtastic tracker configs and the most recent tracker status."""

    def __init__(self, hass: HomeAssistant | None = None) -> None:
        """Initialise the registry."""
        self._hass = hass
        self._store = (
            Store(hass, STORAGE_VERSION, STORAGE_KEY)
            if hass is not None and Store is not None
            else None
        )
        self._configs: dict[str, dict[str, Any]] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[str, str], None]] = []

    async def async_load(self) -> None:
        """Load persisted geofence configs from Home Assistant storage."""
        if self._store is None:
            return

        stored = await self._store.async_load() or {}
        configs = stored.get("configs", {})
        if not isinstance(configs, dict):
            return

        for tracker_id, config in configs.items():
            if not isinstance(config, dict):
                continue
            person_name = config.get("person_name")
            if not person_name:
                continue
            self._configs[str(tracker_id)] = config

    async def _async_save(self) -> None:
        """Persist geofence configs to Home Assistant storage."""
        if self._store is None:
            return
        await self._store.async_save({"configs": self._configs})

    async def async_register_geofence(self, config: dict[str, Any]) -> None:
        """Persist and publish a tracker geofence config."""
        tracker_id = str(config["tracker_id"])
        person_name = str(config["person_name"])
        self._configs[tracker_id] = dict(config)
        await self._async_save()
        self._notify_registration_listeners(tracker_id, person_name)

    def register(self, tracker_id: str, person_name: str) -> None:
        """Register a tracker → person mapping without persistence."""
        config = self._configs.get(tracker_id, {})
        config.setdefault("tracker_id", tracker_id)
        config["person_name"] = person_name
        self._configs[tracker_id] = config
        self._notify_registration_listeners(tracker_id, person_name)

    def _notify_registration_listeners(self, tracker_id: str, person_name: str) -> None:
        """Notify tracker registration listeners."""
        for listener in list(self._listeners):
            try:
                listener(tracker_id, person_name)
            except Exception:
                _LOGGER.exception("Error in tracker registry listener")

    def get_person(self, tracker_id: str) -> str | None:
        """Return the person name for a tracker ID."""
        config = self._configs.get(tracker_id)
        if config is None:
            return None
        person_name = config.get("person_name")
        return str(person_name) if person_name else None

    def get_config(self, tracker_id: str) -> dict[str, Any] | None:
        """Return the persisted geofence config for a tracker."""
        config = self._configs.get(tracker_id)
        return dict(config) if config is not None else None

    def get_last_status(self, tracker_id: str) -> dict[str, Any] | None:
        """Return the most recent tracker status payload."""
        status = self._statuses.get(tracker_id)
        return dict(status) if status is not None else None

    def set_last_status(self, tracker_id: str, status: dict[str, Any]) -> dict[str, Any] | None:
        """Store and return the previous status payload for a tracker."""
        previous = self._statuses.get(tracker_id)
        self._statuses[tracker_id] = dict(status)
        return dict(previous) if previous is not None else None

    def add_listener(self, listener: Callable[[str, str], None]) -> None:
        """Register a listener for tracker registration changes."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[str, str], None]) -> None:
        """Remove a listener."""
        try:
            self._listeners.remove(listener)
        except ValueError:
            return

    @property
    def tracker_ids(self) -> list[str]:
        """Return all known tracker IDs."""
        return list(self._configs.keys())


CONFIGURE_TRACKER_GEOFENCE_SCHEMA = vol.Schema(
    {
        vol.Required("tracker_id"): cv.string,
        vol.Required("person_name"): cv.string,
        vol.Required("polygon"): vol.All(
            list,
            vol.Length(min=3),
            [vol.All(list, vol.Length(min=2, max=2))],
        ),
        vol.Optional("geofence_name"): cv.string,
        vol.Optional("relay_entity"): cv.entity_id,
        vol.Optional("enable_beeper", default=DEFAULT_ENABLE_BEEPER): vol.Boolean(),
        vol.Optional("buzzer_gpio", default=DEFAULT_BUZZER_GPIO): vol.Coerce(int),
        vol.Optional(
            "warn_dist_approaching",
            default=DEFAULT_WARN_DIST_APPROACHING,
        ): vol.Coerce(int),
        vol.Optional("warn_dist_near", default=DEFAULT_WARN_DIST_NEAR): vol.Coerce(int),
        vol.Optional(
            "warn_dist_critical",
            default=DEFAULT_WARN_DIST_CRITICAL,
        ): vol.Coerce(int),
    }
)


def _fire_config_error(
    hass: HomeAssistant,
    tracker_id: str,
    person_name: str,
    message: str,
) -> None:
    """Publish a geofence configuration error event."""
    hass.bus.async_fire(
        "frigate_identity.geofence_config_error",
        {
            "tracker_id": tracker_id,
            "person_name": person_name,
            "error": message,
        },
    )


async def async_handle_configure_tracker_geofence(
    hass: HomeAssistant,
    call: ServiceCall,
    tracker_registry: TrackerRegistry,
) -> None:
    """Handle the configure_tracker_geofence service call."""
    tracker_id = str(call.data["tracker_id"])
    person_name = str(call.data["person_name"])
    polygon = _normalize_polygon(call.data["polygon"])
    validation_error = _validate_polygon(polygon)
    if validation_error:
        _fire_config_error(hass, tracker_id, person_name, validation_error)
        raise HomeAssistantError(validation_error)

    if hasattr(hass.services, "has_service") and not hass.services.has_service(
        MESHTASTIC_DOMAIN,
        MESHTASTIC_SERVICE_SEND,
    ):
        message = "Meshtastic integration is not available"
        _fire_config_error(hass, tracker_id, person_name, message)
        raise HomeAssistantError(message)

    config = _build_geofence_config(hass, call, polygon)
    payload = _build_tracker_payload(config)
    payload_json = _encode_payload(payload)

    if len(payload_json.encode()) > MAX_DIRECT_MESSAGE_BYTES:
        message = _message_size_error(payload_json)
        _fire_config_error(hass, tracker_id, person_name, message)
        raise HomeAssistantError(message)

    last_error: Exception | None = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            _LOGGER.debug(
                "Sending geofence config to tracker %s (%d bytes, attempt %d/%d)",
                tracker_id,
                len(payload_json.encode()),
                attempt,
                MAX_SEND_ATTEMPTS,
            )
            await hass.services.async_call(
                MESHTASTIC_DOMAIN,
                MESHTASTIC_SERVICE_SEND,
                {"target": tracker_id, "message": payload_json},
                blocking=True,
            )
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _LOGGER.warning(
                "Failed to send Meshtastic geofence config to %s on attempt %d/%d: %s",
                tracker_id,
                attempt,
                MAX_SEND_ATTEMPTS,
                exc,
            )

    if last_error is not None:
        message = f"Failed to send geofence config to tracker: {last_error}"
        _fire_config_error(hass, tracker_id, person_name, message)
        raise HomeAssistantError(message)

    await tracker_registry.async_register_geofence(config)
    hass.bus.async_fire(
        "frigate_identity.geofence_config_sent",
        {
            "tracker_id": tracker_id,
            "person_name": person_name,
            "geofence_name": config["geofence_name"] or f"{person_name}_geofence",
            "polygon_points": len(polygon),
            "enable_beeper": config["enable_beeper"],
        },
    )


def _fire_tracker_events(
    hass: HomeAssistant,
    tracker_id: str,
    person_name: str,
    previous_status: dict[str, Any] | None,
    status: dict[str, Any],
) -> None:
    """Fire geofence-related HA events from a tracker status update."""
    event_data = {
        "tracker_id": tracker_id,
        "person_name": person_name,
        "latitude": status.get("latitude"),
        "longitude": status.get("longitude"),
        "distance_to_boundary": status.get("dist_to_boundary"),
        "beep_zone": status.get("beep_zone"),
        "battery_percent": status.get("battery_percent"),
        "gps_fix": status.get("gps_fix"),
        "timestamp": status.get("timestamp"),
    }

    previous_geofence = (previous_status or {}).get("status")
    current_geofence = status.get("status")
    if current_geofence == "in_geofence" and previous_geofence != "in_geofence":
        hass.bus.async_fire("frigate_identity.tracker_entered_geofence", event_data)
    elif (
        current_geofence == "outside_geofence"
        and previous_geofence != "outside_geofence"
    ):
        hass.bus.async_fire("frigate_identity.tracker_exited_geofence", event_data)

    previous_battery = (previous_status or {}).get("battery_percent")
    battery_percent = status.get("battery_percent")
    if (
        isinstance(battery_percent, (int, float))
        and battery_percent < LOW_BATTERY_THRESHOLD
        and (
            not isinstance(previous_battery, (int, float))
            or previous_battery >= LOW_BATTERY_THRESHOLD
        )
    ):
        hass.bus.async_fire("frigate_identity.tracker_battery_low", event_data)

    previous_fix = (previous_status or {}).get("gps_fix")
    if status.get("gps_fix") is False and previous_fix is not False:
        hass.bus.async_fire("frigate_identity.tracker_no_gps_fix", event_data)


async def async_setup_tracker_sensors(
    hass: HomeAssistant,
    tracker_registry: TrackerRegistry,
    async_add_entities: AddEntitiesCallback,
) -> Callable[[], None]:
    """Set up tracker status sensors and Meshtastic event listeners."""
    tracked: set[str] = set()
    geofence_sensors: dict[str, FrigateIdentityTrackerGeofenceStatusSensor] = {}
    distance_sensors: dict[str, FrigateIdentityTrackerDistanceSensor] = {}
    beep_zone_sensors: dict[str, FrigateIdentityTrackerBeepZoneSensor] = {}
    battery_sensors: dict[str, FrigateIdentityTrackerBatterySensor] = {}
    position_sensors: dict[str, FrigateIdentityTrackerPositionSensor] = {}
    relay_sensors: dict[str, FrigateIdentityTrackerRelaySensor] = {}
    last_update_sensors: dict[str, FrigateIdentityTrackerLastUpdateSensor] = {}

    def _create_sensors_for_tracker(tracker_id: str, person_name: str) -> None:
        if tracker_id in tracked:
            return

        tracked.add(tracker_id)
        config = tracker_registry.get_config(tracker_id) or {
            "tracker_id": tracker_id,
            "person_name": person_name,
        }
        entities: list[_TrackerSensorBase] = [
            FrigateIdentityTrackerGeofenceStatusSensor(tracker_id, person_name, config),
            FrigateIdentityTrackerDistanceSensor(tracker_id, person_name, config),
            FrigateIdentityTrackerBeepZoneSensor(tracker_id, person_name, config),
            FrigateIdentityTrackerBatterySensor(tracker_id, person_name, config),
            FrigateIdentityTrackerPositionSensor(tracker_id, person_name, config),
            FrigateIdentityTrackerRelaySensor(tracker_id, person_name, config),
            FrigateIdentityTrackerLastUpdateSensor(tracker_id, person_name, config),
        ]

        geofence_sensors[tracker_id] = entities[0]
        distance_sensors[tracker_id] = entities[1]
        beep_zone_sensors[tracker_id] = entities[2]
        battery_sensors[tracker_id] = entities[3]
        position_sensors[tracker_id] = entities[4]
        relay_sensors[tracker_id] = entities[5]
        last_update_sensors[tracker_id] = entities[6]

        async_add_entities(entities)

        status = tracker_registry.get_last_status(tracker_id)
        if status is not None:
            for entity in entities:
                entity.update_from_status(status)

    tracker_registry.add_listener(_create_sensors_for_tracker)

    for tracker_id in tracker_registry.tracker_ids:
        person_name = tracker_registry.get_person(tracker_id)
        if person_name:
            _create_sensors_for_tracker(tracker_id, person_name)

    @callback
    def _on_meshtastic_message(event: Event) -> None:
        event_data = event.data or {}
        candidates = _status_candidates(event_data)
        if not candidates:
            return

        for status in candidates:
            tracker_id = _extract_tracker_id(event_data, status)
            if not tracker_id:
                continue

            previous_status = tracker_registry.set_last_status(tracker_id, status)
            person_name = tracker_registry.get_person(tracker_id)
            if person_name is None:
                _LOGGER.debug(
                    "Buffered status for Meshtastic tracker %s before geofence registration",
                    tracker_id,
                )
                continue

            if tracker_id in geofence_sensors:
                geofence_sensors[tracker_id].update_from_status(status)
                distance_sensors[tracker_id].update_from_status(status)
                beep_zone_sensors[tracker_id].update_from_status(status)
                battery_sensors[tracker_id].update_from_status(status)
                position_sensors[tracker_id].update_from_status(status)
                relay_sensors[tracker_id].update_from_status(status)
                last_update_sensors[tracker_id].update_from_status(status)

            _fire_tracker_events(hass, tracker_id, person_name, previous_status, status)

    unsub_bus = hass.bus.async_listen(MESHTASTIC_EVENT_MESSAGE, _on_meshtastic_message)

    def _cleanup() -> None:
        unsub_bus()
        tracker_registry.remove_listener(_create_sensors_for_tracker)

    return _cleanup


class _TrackerSensorBase(SensorEntity):
    """Base class for Meshtastic tracker sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        tracker_id: str,
        person_name: str,
        suffix: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the sensor."""
        self._tracker_id = tracker_id
        self._person_name = person_name
        self._config = dict(config or {})
        slug = person_name.lower().replace(" ", "_").replace("-", "_")
        suffix_slug = suffix.lower().replace(" ", "_")
        self._attr_name = f"{person_name} {suffix}"
        self._attr_unique_id = f"frigate_identity_{slug}_{suffix_slug}"
        self._attr_extra_state_attributes: dict[str, Any] = {"tracker_id": tracker_id}

    def _common_attributes(self, status: dict[str, Any]) -> dict[str, Any]:
        """Build common tracker attributes shared by all sensors."""
        return {
            "tracker_id": self._tracker_id,
            "geofence_name": self._config.get("geofence_name"),
            "polygon": self._config.get("polygon"),
            "relay_entity": self._config.get("relay_entity"),
            "enable_beeper": self._config.get("enable_beeper"),
            "buzzer_gpio": self._config.get("buzzer_gpio"),
            "warn_dist_approaching": self._config.get("warn_dist_approaching"),
            "warn_dist_near": self._config.get("warn_dist_near"),
            "warn_dist_critical": self._config.get("warn_dist_critical"),
            "gps_fix": status.get("gps_fix"),
            "timestamp": status.get("timestamp"),
            "last_update": _coerce_timestamp(status.get("timestamp")),
        }

    def update_from_status(self, status: dict[str, Any]) -> None:
        """Update sensor state from tracker status."""
        raise NotImplementedError


class FrigateIdentityTrackerGeofenceStatusSensor(_TrackerSensorBase):
    """Reports whether the tracker is inside or outside the geofence."""

    def __init__(self, tracker_id: str, person_name: str, config: dict[str, Any]) -> None:
        super().__init__(tracker_id, person_name, "Geofence Status", config)
        self._attr_native_value = "unknown"

    def update_from_status(self, status: dict[str, Any]) -> None:
        geofence_status = status.get("status")
        if geofence_status in {"in_geofence", "outside_geofence"}:
            self._attr_native_value = geofence_status
        self._attr_extra_state_attributes = self._common_attributes(status)
        self.async_write_ha_state()


class FrigateIdentityTrackerDistanceSensor(_TrackerSensorBase):
    """Reports the tracker distance to the geofence boundary in metres."""

    _attr_native_unit_of_measurement = "m"

    def __init__(self, tracker_id: str, person_name: str, config: dict[str, Any]) -> None:
        super().__init__(tracker_id, person_name, "Distance To Boundary", config)
        self._attr_native_value: float | None = None

    def update_from_status(self, status: dict[str, Any]) -> None:
        distance = status.get("dist_to_boundary")
        if isinstance(distance, (int, float)):
            self._attr_native_value = float(distance)
        self._attr_extra_state_attributes = self._common_attributes(status)
        self.async_write_ha_state()


class FrigateIdentityTrackerBeepZoneSensor(_TrackerSensorBase):
    """Reports the tracker beep zone."""

    def __init__(self, tracker_id: str, person_name: str, config: dict[str, Any]) -> None:
        super().__init__(tracker_id, person_name, "Beep Zone", config)
        self._attr_native_value = "unknown"

    def update_from_status(self, status: dict[str, Any]) -> None:
        beep_zone = status.get("beep_zone")
        if isinstance(beep_zone, str) and beep_zone:
            self._attr_native_value = beep_zone
        self._attr_extra_state_attributes = self._common_attributes(status)
        self.async_write_ha_state()


class FrigateIdentityTrackerBatterySensor(_TrackerSensorBase):
    """Reports tracker battery percentage."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, tracker_id: str, person_name: str, config: dict[str, Any]) -> None:
        super().__init__(tracker_id, person_name, "Battery Percent", config)
        self._attr_native_value: int | None = None

    def update_from_status(self, status: dict[str, Any]) -> None:
        battery_percent = status.get("battery_percent")
        if isinstance(battery_percent, (int, float)):
            self._attr_native_value = int(battery_percent)
        self._attr_extra_state_attributes = self._common_attributes(status)
        self.async_write_ha_state()


class FrigateIdentityTrackerPositionSensor(_TrackerSensorBase):
    """Reports the last known GPS position."""

    def __init__(self, tracker_id: str, person_name: str, config: dict[str, Any]) -> None:
        super().__init__(tracker_id, person_name, "Last Position", config)
        self._attr_native_value: str | None = None

    def update_from_status(self, status: dict[str, Any]) -> None:
        latitude = status.get("latitude")
        longitude = status.get("longitude")
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            self._attr_native_value = f"{latitude},{longitude}"
        self._attr_extra_state_attributes = {
            **self._common_attributes(status),
            "latitude": latitude,
            "longitude": longitude,
        }
        self.async_write_ha_state()


class FrigateIdentityTrackerRelaySensor(_TrackerSensorBase):
    """Reports the relay state reported by the tracker."""

    def __init__(self, tracker_id: str, person_name: str, config: dict[str, Any]) -> None:
        super().__init__(tracker_id, person_name, "Relay State", config)
        self._attr_native_value = "off"

    def update_from_status(self, status: dict[str, Any]) -> None:
        relay_enabled = status.get("relay_enabled")
        if relay_enabled is True:
            self._attr_native_value = "on"
        elif relay_enabled is False:
            self._attr_native_value = "off"
        self._attr_extra_state_attributes = {
            **self._common_attributes(status),
            "relay_enabled": relay_enabled,
        }
        self.async_write_ha_state()


class FrigateIdentityTrackerLastUpdateSensor(_TrackerSensorBase):
    """Reports the tracker timestamp as an ISO-8601 string."""

    if _TIMESTAMP_DEVICE_CLASS is not None:
        _attr_device_class = _TIMESTAMP_DEVICE_CLASS

    def __init__(self, tracker_id: str, person_name: str, config: dict[str, Any]) -> None:
        super().__init__(tracker_id, person_name, "Last Update", config)
        self._attr_native_value: str | None = None

    def update_from_status(self, status: dict[str, Any]) -> None:
        self._attr_native_value = _coerce_timestamp(status.get("timestamp"))
        self._attr_extra_state_attributes = self._common_attributes(status)
        self.async_write_ha_state()
