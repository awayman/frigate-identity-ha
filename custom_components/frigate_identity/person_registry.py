"""Person registry for Frigate Identity.

Manages person discovery from MQTT messages and persons.yaml metadata.
Provides a shared registry that all platforms (sensor, camera, binary_sensor)
use to dynamically create and remove entities.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_FRIGATE_IDENTITY_IS_CHILD,
    ATTR_FRIGATE_IDENTITY_SAFE_ZONES,
    DATA_CAMERA_ZONES,
    DATA_PERSONS,
    DATA_PERSONS_META,
    DOMAIN,
    EVENT_PERSONS_UPDATED,
    SERVICE_HEARTBEAT_STALE_THRESHOLD_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


def _slug(name: str) -> str:
    """Return a lowercase underscore-separated entity slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


def is_child(meta: dict[str, Any]) -> bool:
    """Return True if person metadata marks them as a child."""
    return meta.get("role") == "child" or bool(meta.get("requires_supervision"))


def is_adult(meta: dict[str, Any]) -> bool:
    """Return True if person metadata marks them as a trusted adult."""
    return meta.get("role") == "trusted_adult" or bool(meta.get("can_supervise"))


class PersonData:
    """Data for a single tracked person."""

    def __init__(self, name: str) -> None:
        """Initialise person data."""
        self.name = name
        self.slug = _slug(name)
        self.camera: str | None = None
        self.confidence: float | None = None
        self.source: str | None = None
        self.frigate_zones: list[str] = []
        self.event_id: str | None = None
        self.snapshot_url: str | None = None
        self.timestamp: int | None = None
        self.last_seen: str | None = None
        self.similarity_score: float | None = None
        self.event_history: list[dict[str, Any]] = []  # Last 10 events with event_id, timestamp, camera, confidence
        self.is_child: bool = False  # Mark as child for supervision logic
        self.safe_zones: list[str] = []  # Zones where child can be alone (empty = all zones require supervision)

    def update_from_payload(self, payload: dict[str, Any]) -> None:
        """Update person data from an MQTT message payload."""
        self.camera = payload.get("camera") or payload.get("checkpoint")
        self.confidence = payload.get("confidence")
        self.source = payload.get("source")
        self.frigate_zones = payload.get("frigate_zones", [])
        self.event_id = payload.get("event_id")
        self.snapshot_url = payload.get("snapshot_url")
        self.timestamp = payload.get("timestamp")
        self.last_seen = datetime.now().isoformat()
        if payload.get("similarity_score") is not None:
            self.similarity_score = payload["similarity_score"]
        
        # Add to event history (circular buffer of 10)
        if self.event_id and self.timestamp:
            event_entry = {
                "event_id": self.event_id,
                "timestamp": self.timestamp,
                "camera": self.camera,
                "confidence": self.confidence,
            }
            self.event_history.insert(0, event_entry)  # Prepend (most recent first)
            if len(self.event_history) > 10:
                self.event_history.pop()  # Keep only 10 most recent

    def as_dict(self) -> dict[str, Any]:
        """Return person data as a serialisable dict."""
        data: dict[str, Any] = {
            "camera": self.camera,
            "confidence": self.confidence,
            "source": self.source,
            "frigate_zones": self.frigate_zones,
            "event_id": self.event_id,
            "snapshot_url": self.snapshot_url,
            "timestamp": self.timestamp,
            "last_seen": self.last_seen,
            "event_history": self.event_history,
        }
        if self.similarity_score is not None:
            data["similarity_score"] = self.similarity_score
        return data


class PersonRegistry:
    """Central registry of all tracked persons.

    Merges MQTT-discovered persons with persons.yaml metadata.
    Notifies platforms when the person list changes so they can
    add/remove entities dynamically.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the registry."""
        self.hass = hass
        self._persons: dict[str, PersonData] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._camera_zones: dict[str, str] = {}
        self._listeners: list[callback] = []
        self._discovered_zones: set[str] = set()  # Track all zones from Frigate MQTT
        self._last_heartbeat_timestamp: datetime | None = None

    @property
    def persons(self) -> dict[str, PersonData]:
        """Return all tracked persons."""
        return self._persons

    @property
    def person_names(self) -> list[str]:
        """Return sorted list of all known person names."""
        return sorted(self._persons.keys())

    @property
    def meta(self) -> dict[str, dict[str, Any]]:
        """Return persons metadata from persons.yaml."""
        return self._meta

    @property
    def camera_zones(self) -> dict[str, str]:
        """Return camera_zones overrides from persons.yaml."""
        return self._camera_zones

    @property
    def discovered_zones(self) -> list[str]:
        """Return sorted list of all discovered Frigate zones."""
        return sorted(self._discovered_zones)

    def adults(self) -> list[str]:
        """Return names of trusted adults."""
        return [n for n, p in self._persons.items() if not p.is_child]

    def children(self) -> list[str]:
        """Return names of children requiring supervision."""
        return [n for n, p in self._persons.items() if p.is_child]

    def children_with_safe_zones(self) -> dict[str, list[str]]:
        """Return {child_name: [safe_zones]} for children with safe zones defined."""
        result: dict[str, list[str]] = {}
        for name, person in self._persons.items():
            if person.is_child and person.safe_zones:
                result[name] = list(person.safe_zones)
        return result

    def get_person(self, name: str) -> PersonData | None:
        """Get person data by name."""
        return self._persons.get(name)

    def get_child_safe_zones(self, name: str) -> list[str]:
        """Get safe zones for a child, or empty list if not a child."""
        person = self._persons.get(name)
        if person and person.is_child:
            return person.safe_zones
        return []

    def is_child_in_safe_zone(self, name: str, current_zone: str) -> bool:
        """Check if a child is in one of their safe zones."""
        person = self._persons.get(name)
        if not person or not person.is_child:
            return False
        # If no safe zones defined, child is not in a safe zone (requires adult)
        if not person.safe_zones:
            return False
        return current_zone in person.safe_zones

    def register_listener(self, listener: callback) -> callback:
        """Register a callback for person list changes. Returns unregister callable."""
        self._listeners.append(listener)

        @callback
        def _unregister() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unregister

    def get_service_health(self) -> dict[str, Any]:
        """Return current identity service health based on heartbeat age."""
        if self._last_heartbeat_timestamp is None:
            return {
                "status": "initializing",
                "last_heartbeat_age_seconds": None,
                "is_connected": False,
                "last_heartbeat_timestamp": None,
            }

        age_seconds = int(
            (datetime.now() - self._last_heartbeat_timestamp).total_seconds()
        )
        is_connected = age_seconds < SERVICE_HEARTBEAT_STALE_THRESHOLD_SECONDS

        return {
            "status": "running" if is_connected else "stale",
            "last_heartbeat_age_seconds": age_seconds,
            "is_connected": is_connected,
            "last_heartbeat_timestamp": self._last_heartbeat_timestamp.isoformat(),
        }

    @callback
    def async_update_heartbeat(self) -> None:
        """Record a heartbeat from the identity service."""
        self._last_heartbeat_timestamp = datetime.now()
        self.hass.async_create_task(self._async_notify_listeners(fire_event=False))

    async def async_load_persons_from_ha(self) -> None:
        """Load person metadata from HA person entity registry."""
        _LOGGER.debug("=== LOADING PERSONS FROM HA ===")
        registry = er.async_get(self.hass)
        
        # Look for person entities and load custom attributes
        new_persons = False
        person_count = 0
        for ent_id, entry in registry.entities.items():
            if entry.domain != "person":
                continue
            
            person_count += 1
            person_name = entry.name or entry.original_name
            if not person_name:
                _LOGGER.warning("Person entity %s has no name, skipping", ent_id)
                continue
                
            # Get the person entity state
            entity_state = self.hass.states.get(ent_id)
            if not entity_state:
                _LOGGER.warning("Person entity %s has no state, skipping", ent_id)
                continue
            
            # Create or get person data
            if person_name not in self._persons:
                self._persons[person_name] = PersonData(person_name)
                new_persons = True
                _LOGGER.debug("Loaded person from HA: %s", person_name)
            
            person = self._persons[person_name]
            
            # Read custom attributes from entity
            person.is_child = entity_state.attributes.get(
                ATTR_FRIGATE_IDENTITY_IS_CHILD, False
            )
            person.safe_zones = entity_state.attributes.get(
                ATTR_FRIGATE_IDENTITY_SAFE_ZONES, []
            )
        
        if new_persons:
            await self._async_notify_listeners()
        
        _LOGGER.debug(
            "Loaded %d person(s) from %d HA person entities",
            len(self._persons),
            person_count,
        )
        _LOGGER.debug("=== PERSON LOAD COMPLETE ===")

    @callback
    def async_update_person(self, name: str, payload: dict[str, Any]) -> None:
        """Update or create a person from an MQTT message."""
        is_new = name not in self._persons
        if is_new:
            self._persons[name] = PersonData(name)
            # Default MQTT-discovered people to trusted_adult (not child)
            # User must explicitly configure them as children via config flow or service
            self._persons[name].is_child = False
            _LOGGER.info("Discovered new person via MQTT: %s", name)

        self._persons[name].update_from_payload(payload)
        
        # Track discovered zones
        zones = payload.get("frigate_zones", [])
        if zones:
            for zone in zones:
                self._discovered_zones.add(zone)

        # Always notify listeners so dynamic entities can refresh state.
        # Only fire the dashboard/person-list changed event for newly
        # discovered persons to avoid frequent Lovelace refresh prompts.
        self.hass.async_create_task(self._async_notify_listeners(fire_event=is_new))

    async def _async_notify_listeners(self, *, fire_event: bool = True) -> None:
        """Notify all listeners that the person list changed."""
        # Store in hass.data for easy access by other components
        self.hass.data.setdefault(DOMAIN, {})[DATA_PERSONS] = self._persons
        self.hass.data[DOMAIN][DATA_PERSONS_META] = self._meta
        self.hass.data[DOMAIN][DATA_CAMERA_ZONES] = self._camera_zones

        if fire_event:
            self.hass.bus.async_fire(EVENT_PERSONS_UPDATED, {
                "persons": list(self._persons.keys()),
            })

        for listener in self._listeners:
            try:
                listener()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in person registry listener")
