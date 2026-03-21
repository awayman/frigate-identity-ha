"""Sensor platform for Frigate Identity.

Provides:
  - FrigateIdentityLastPersonSensor  — last detected person name + attributes
  - FrigateIdentityAllPersonsSensor  — count of all tracked persons + dict
  - FrigateIdentityPersonLocationSensor  — per-person: state = camera, attrs = zones etc.

The first two are created once at setup.  Per-person sensors are created
dynamically via the PersonRegistry as persons are discovered from MQTT or
persons.yaml.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MQTT_TOPIC_PREFIX,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DOMAIN,
    TOPIC_PERSON_WILDCARD,
    TOPIC_SNAPSHOTS_WILDCARD,
)
from .person_registry import PersonData, PersonRegistry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frigate Identity sensor platform."""
    config = {**config_entry.data, **config_entry.options}
    prefix = config.get(CONF_MQTT_TOPIC_PREFIX, DEFAULT_MQTT_TOPIC_PREFIX)
    registry: PersonRegistry = hass.data[DOMAIN]["registry"]

    # ── Global sensors (always present) ─────────────────────────────────
    last_person = FrigateIdentityLastPersonSensor(prefix, registry)
    all_persons = FrigateIdentityAllPersonsSensor(prefix, registry)
    snapshot_debug = FrigateIdentitySnapshotDebugSensor(prefix)
    async_add_entities([last_person, all_persons, snapshot_debug])

    # ── Dynamic per-person location sensors ─────────────────────────────
    tracked: dict[str, FrigateIdentityPersonLocationSensor] = {}

    @callback
    def _on_persons_changed() -> None:
        """Create location sensors for newly discovered persons."""
        new_entities: list[FrigateIdentityPersonLocationSensor] = []
        for name in registry.person_names:
            if name not in tracked:
                entity = FrigateIdentityPersonLocationSensor(name, registry)
                tracked[name] = entity
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    unsub = registry.register_listener(_on_persons_changed)
    config_entry.async_on_unload(unsub)

    # Create entities for persons already known from persons.yaml
    _on_persons_changed()


# ╭───────────────────────────────────────────────────────────────────────╮
# │  Global sensors                                                       │
# ╰───────────────────────────────────────────────────────────────────────╯


class FrigateIdentityLastPersonSensor(SensorEntity):
    """Reports the last recognised person from identity MQTT topics."""

    _attr_has_entity_name = True

    def __init__(self, prefix: str, registry: PersonRegistry) -> None:
        """Initialise the sensor."""
        self._attr_name = "Frigate Identity - Last Person"
        self._attr_unique_id = "frigate_identity_last_person"
        self._attr_native_value: str | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._prefix = prefix
        self._registry = registry
        self._unsubs: list[Any] = []

    @staticmethod
    def _extract_person(payload: dict[str, Any], topic: str | None = None) -> str | None:
        """Extract person name from payload, then topic fallback."""
        person = (
            payload.get("person_id")
            or payload.get("person")
            or payload.get("name")
        )
        if person:
            return str(person)

        if topic and "/snapshots/" in topic and topic.endswith("/metadata"):
            try:
                suffix = topic.split("/snapshots/", 1)[1]
            except IndexError:
                return None
            if suffix.endswith("/metadata"):
                return suffix[: -len("/metadata")]

        return None

    @staticmethod
    def _normalize_snapshot_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        """Map snapshot metadata fields to person payload schema."""
        normalized = dict(payload)
        if "frigate_zones" not in normalized and isinstance(payload.get("zones"), list):
            normalized["frigate_zones"] = payload["zones"]
        return normalized

    async def async_added_to_hass(self) -> None:
        """Subscribe to identity MQTT topics."""
        person_topic = TOPIC_PERSON_WILDCARD.format(prefix=self._prefix)
        snapshots_topic = TOPIC_SNAPSHOTS_WILDCARD.format(prefix=self._prefix)

        @callback
        def _mqtt_person_message(msg: Any) -> None:
            try:
                payload = json.loads(msg.payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Failed to parse MQTT payload on %s", msg.topic)
                return

            person = self._extract_person(payload)
            if not person:
                return

            # Update the person in the registry
            self._registry.async_update_person(person, payload)

            self._attr_native_value = person
            self._attr_extra_state_attributes = {
                "confidence": payload.get("confidence"),
                "camera": payload.get("camera") or payload.get("checkpoint"),
                "timestamp": payload.get("timestamp"),
                "source": payload.get("source"),
                "frigate_zones": payload.get("frigate_zones", []),
                "event_id": payload.get("event_id"),
                "snapshot_url": payload.get("snapshot_url"),
                "last_updated": datetime.now().isoformat(),
            }
            if payload.get("similarity_score") is not None:
                self._attr_extra_state_attributes["similarity_score"] = payload[
                    "similarity_score"
                ]
            self.async_write_ha_state()

        @callback
        def _mqtt_snapshot_metadata_message(msg: Any) -> None:
            if not msg.topic.startswith(f"{self._prefix}/snapshots/") or not msg.topic.endswith("/metadata"):
                return

            try:
                payload = json.loads(msg.payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Failed to parse snapshot metadata payload on %s", msg.topic)
                return

            person = self._extract_person(payload, msg.topic)
            if not person:
                return

            normalized_payload = self._normalize_snapshot_metadata(payload)
            self._registry.async_update_person(person, normalized_payload)

            self._attr_native_value = person
            self._attr_extra_state_attributes = {
                "confidence": normalized_payload.get("confidence"),
                "camera": normalized_payload.get("camera")
                or normalized_payload.get("checkpoint"),
                "timestamp": normalized_payload.get("timestamp"),
                "source": normalized_payload.get("source")
                or "snapshot_metadata",
                "frigate_zones": normalized_payload.get("frigate_zones", []),
                "event_id": normalized_payload.get("event_id"),
                "snapshot_url": normalized_payload.get("snapshot_url"),
                "last_updated": datetime.now().isoformat(),
            }
            if normalized_payload.get("similarity_score") is not None:
                self._attr_extra_state_attributes["similarity_score"] = normalized_payload[
                    "similarity_score"
                ]
            self.async_write_ha_state()

        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, person_topic, _mqtt_person_message)
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, snapshots_topic, _mqtt_snapshot_metadata_message
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT."""
        for unsub in self._unsubs:
            if callable(unsub):
                unsub()
        self._unsubs = []


class FrigateIdentityAllPersonsSensor(SensorEntity):
    """Tracks all currently detected persons with their locations."""

    _attr_has_entity_name = True

    def __init__(self, prefix: str, registry: PersonRegistry) -> None:
        """Initialise the sensor."""
        self._attr_name = "Frigate Identity - All Persons"
        self._attr_unique_id = "frigate_identity_all_persons"
        self._attr_native_value: int = 0
        self._attr_extra_state_attributes: dict[str, Any] = {"persons": {}}
        self._prefix = prefix
        self._registry = registry
        self._unsub: Any = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to identity MQTT topics."""
        topic = TOPIC_PERSON_WILDCARD.format(prefix=self._prefix)

        @callback
        def _mqtt_message(msg: Any) -> None:
            try:
                payload = json.loads(msg.payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Failed to parse MQTT payload on %s", msg.topic)
                return

            person_id = (
                payload.get("person_id")
                or payload.get("person")
                or payload.get("name")
            )
            if not person_id:
                return

            # Registry is already updated by LastPersonSensor; just refresh state
            persons_dict = {
                name: pd.as_dict()
                for name, pd in self._registry.persons.items()
            }
            self._attr_native_value = len(persons_dict)
            self._attr_extra_state_attributes = {"persons": persons_dict}
            self.async_write_ha_state()

        self._unsub = await mqtt.async_subscribe(
            self.hass, topic, _mqtt_message
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT."""
        if callable(self._unsub):
            self._unsub()


class FrigateIdentitySnapshotDebugSensor(SensorEntity):
    """Tracks incoming snapshot MQTT activity for troubleshooting."""

    _attr_has_entity_name = True

    def __init__(self, prefix: str) -> None:
        """Initialise the sensor."""
        self._attr_name = "Frigate Identity - Snapshot Debug"
        self._attr_unique_id = "frigate_identity_snapshot_debug"
        self._attr_native_value: int = 0
        self._attr_extra_state_attributes: dict[str, Any] = {
            "last_snapshot_topic": None,
            "last_snapshot_person": None,
            "last_snapshot_received": None,
            "last_snapshot_bytes": 0,
            "snapshot_messages": 0,
            "metadata_messages": 0,
            "last_metadata_topic": None,
            "last_metadata_received": None,
        }
        self._prefix = prefix
        self._topic_root = f"{prefix}/snapshots/"
        self._unsub: Any = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to snapshot MQTT topics."""
        topic = TOPIC_SNAPSHOTS_WILDCARD.format(prefix=self._prefix)

        @callback
        def _mqtt_message(msg: Any) -> None:
            if not msg.topic.startswith(self._topic_root):
                return

            suffix = msg.topic[len(self._topic_root) :]
            now_iso = datetime.now().isoformat()

            if suffix.endswith("/metadata"):
                self._attr_extra_state_attributes["metadata_messages"] += 1
                self._attr_extra_state_attributes["last_metadata_topic"] = msg.topic
                self._attr_extra_state_attributes["last_metadata_received"] = now_iso
                self.async_write_ha_state()
                return

            if "/" in suffix:
                return

            payload_bytes = len(msg.payload or b"")
            self._attr_native_value += 1
            self._attr_extra_state_attributes["snapshot_messages"] = (
                self._attr_native_value
            )
            self._attr_extra_state_attributes["last_snapshot_topic"] = msg.topic
            self._attr_extra_state_attributes["last_snapshot_person"] = suffix
            self._attr_extra_state_attributes["last_snapshot_received"] = now_iso
            self._attr_extra_state_attributes["last_snapshot_bytes"] = payload_bytes
            self.async_write_ha_state()

        self._unsub = await mqtt.async_subscribe(
            self.hass,
            topic,
            _mqtt_message,
            encoding=None,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT."""
        if callable(self._unsub):
            self._unsub()


# ╭───────────────────────────────────────────────────────────────────────╮
# │  Per-person location sensor                                           │
# ╰───────────────────────────────────────────────────────────────────────╯


class FrigateIdentityPersonLocationSensor(SensorEntity):
    """Per-person sensor: state = current camera, attributes = zones etc.

    Replaces the template_sensors.yaml per-person sensor from generate_dashboard.py.
    """

    _attr_has_entity_name = True

    def __init__(self, person_name: str, registry: PersonRegistry) -> None:
        """Initialise the sensor."""
        self._person_name = person_name
        slug = person_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_name = f"{person_name} Location"
        self._attr_unique_id = f"frigate_identity_{slug}_location"
        self._attr_native_value: str | None = "unknown"
        self._attr_extra_state_attributes: dict[str, Any] = {
            "zones": [],
            "confidence": 0,
            "source": "unknown",
            "snapshot_url": "unavailable",
            "last_seen": "unknown",
            "event_history": [],
        }
        self._registry = registry
        self._unsub_listener: Any = None

    async def async_added_to_hass(self) -> None:
        """Start tracking person data changes via the registry."""

        @callback
        def _on_persons_changed() -> None:
            person = self._registry.get_person(self._person_name)
            if person is None:
                return
            self._update_from_person(person)

        self._unsub_listener = self._registry.register_listener(
            _on_persons_changed
        )

        # Also set initial state if data already exists
        person = self._registry.get_person(self._person_name)
        if person and person.camera is not None:
            self._update_from_person(person)

    @callback
    def _update_from_person(self, person: PersonData) -> None:
        """Refresh state from PersonData."""
        self._attr_native_value = person.camera or "unknown"
        self._attr_extra_state_attributes = {
            "zones": person.frigate_zones,
            "confidence": person.confidence or 0,
            "source": person.source or "unknown",
            "snapshot_url": person.snapshot_url or "unavailable",
            "last_seen": person.last_seen or "unknown",
            "event_history": person.event_history,
            "is_child": person.is_child,
            "safe_zones": person.safe_zones,
        }
        if person.similarity_score is not None:
            self._attr_extra_state_attributes["similarity_score"] = (
                person.similarity_score
            )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up."""
        if callable(self._unsub_listener):
            self._unsub_listener()

