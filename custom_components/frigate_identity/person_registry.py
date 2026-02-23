"""Person registry for Frigate Identity.

Manages person discovery from MQTT messages and persons.yaml metadata.
Provides a shared registry that all platforms (sensor, camera, binary_sensor)
use to dynamically create and remove entities.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import yaml

from homeassistant.core import HomeAssistant, callback

from .const import (
    DATA_CAMERA_ZONES,
    DATA_PERSONS,
    DATA_PERSONS_META,
    DOMAIN,
    EVENT_PERSONS_UPDATED,
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

    def adults(self) -> list[str]:
        """Return names of trusted adults."""
        return [n for n, m in self._meta.items() if is_adult(m)]

    def children(self) -> list[str]:
        """Return names of children requiring supervision."""
        return [n for n, m in self._meta.items() if is_child(m)]

    def children_with_danger_zones(self) -> dict[str, list[str]]:
        """Return {child_name: [dangerous_zones]} for children with danger zones."""
        result: dict[str, list[str]] = {}
        for name, meta in self._meta.items():
            if is_child(meta):
                zones = meta.get("dangerous_zones", [])
                if zones:
                    result[name] = list(zones)
        return result

    def get_person(self, name: str) -> PersonData | None:
        """Get person data by name."""
        return self._persons.get(name)

    def register_listener(self, listener: callback) -> callback:
        """Register a callback for person list changes. Returns unregister callable."""
        self._listeners.append(listener)

        @callback
        def _unregister() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unregister

    async def async_load_persons_yaml(self, path: str) -> None:
        """Load person metadata from a persons.yaml file."""
        if not path:
            _LOGGER.debug("No persons file configured; skipping metadata load")
            return

        def _load() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
            if not os.path.isfile(path):
                _LOGGER.warning("Persons file not found: %s", path)
                return {}, {}

            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)

            if not isinstance(data, dict) or "persons" not in data:
                _LOGGER.error("persons.yaml must contain a top-level 'persons' mapping")
                return {}, {}

            raw = data["persons"]
            if not isinstance(raw, dict):
                _LOGGER.error("'persons' must be a mapping of name → attributes")
                return {}, {}

            meta: dict[str, dict[str, Any]] = {}
            for name, attrs in raw.items():
                meta[name] = attrs if isinstance(attrs, dict) else {}

            raw_cz = data.get("camera_zones")
            camera_zones: dict[str, str] = (
                {str(k): str(v) for k, v in raw_cz.items()}
                if isinstance(raw_cz, dict)
                else {}
            )
            return meta, camera_zones

        self._meta, self._camera_zones = await self.hass.async_add_executor_job(
            _load
        )

        # Pre-register persons from YAML so entities are created even before
        # MQTT messages arrive
        new_persons = False
        for name in self._meta:
            if name not in self._persons:
                self._persons[name] = PersonData(name)
                new_persons = True

        if new_persons:
            await self._async_notify_listeners()

        _LOGGER.info(
            "Loaded %d person(s) from %s (adults=%s, children=%s)",
            len(self._meta),
            path,
            self.adults(),
            self.children(),
        )

    @callback
    def async_update_person(self, name: str, payload: dict[str, Any]) -> None:
        """Update or create a person from an MQTT message."""
        is_new = name not in self._persons
        if is_new:
            self._persons[name] = PersonData(name)
            _LOGGER.info("Discovered new person via MQTT: %s", name)

        self._persons[name].update_from_payload(payload)

        if is_new:
            self.hass.async_create_task(self._async_notify_listeners())

    async def _async_notify_listeners(self) -> None:
        """Notify all listeners that the person list changed."""
        # Store in hass.data for easy access by other components
        self.hass.data.setdefault(DOMAIN, {})[DATA_PERSONS] = self._persons
        self.hass.data[DOMAIN][DATA_PERSONS_META] = self._meta
        self.hass.data[DOMAIN][DATA_CAMERA_ZONES] = self._camera_zones

        self.hass.bus.async_fire(EVENT_PERSONS_UPDATED, {
            "persons": list(self._persons.keys()),
        })

        for listener in self._listeners:
            try:
                listener()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in person registry listener")
