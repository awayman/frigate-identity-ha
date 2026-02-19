"""Sensor platform for Frigate Identity."""
import json
import logging
from typing import Any
from datetime import datetime

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

DOMAIN = "frigate_identity"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Frigate Identity sensor platform."""
    async_add_entities([
        FrigateIdentityLastPersonSensor(),
        FrigateIdentityAllPersonsSensor()
    ])


class FrigateIdentityLastPersonSensor(SensorEntity):
    """Sensor that reports the last recognized/tracked person from identity topics."""

    def __init__(self) -> None:
        """Initialize the sensor."""
        self._attr_name = "Frigate Identity - Last Person"
        self._attr_unique_id = "frigate_identity_last_person"
        self._attr_native_value: str | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._unsub = None

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return self._attr_extra_state_attributes

    async def async_added_to_hass(self) -> None:
        """Subscribe to identity MQTT topics when entity is added."""

        @callback
        def _mqtt_message(msg) -> None:
            """Handle MQTT message."""
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.debug("Failed to parse MQTT payload: %s", exc)
                return

            person = (
                payload.get("person_id")
                or payload.get("person")
                or payload.get("name")
            )
            confidence = payload.get("confidence")
            similarity_score = payload.get("similarity_score")
            camera = payload.get("camera") or payload.get("checkpoint")
            timestamp = payload.get("timestamp")
            source = payload.get("source")
            frigate_zones = payload.get("frigate_zones", [])
            event_id = payload.get("event_id")
            snapshot_url = payload.get("snapshot_url")

            self._attr_native_value = person
            self._attr_extra_state_attributes = {
                "confidence": confidence,
                "camera": camera,
                "timestamp": timestamp,
                "source": source,
                "frigate_zones": frigate_zones,
                "event_id": event_id,
                "snapshot_url": snapshot_url,
                "last_updated": datetime.now().isoformat(),
            }

            if similarity_score is not None:
                self._attr_extra_state_attributes["similarity_score"] = similarity_score

            self.async_write_ha_state()

        self._unsub = await mqtt.async_subscribe(
            self.hass, "identity/person/#", _mqtt_message
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT when entity is removed."""
        if callable(self._unsub):
            try:
                self._unsub()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Failed to unsubscribe from MQTT topic")


class FrigateIdentityAllPersonsSensor(SensorEntity):
    """Sensor that tracks all currently detected persons with their locations."""

    def __init__(self) -> None:
        """Initialize the sensor."""
        self._attr_name = "Frigate Identity - All Persons"
        self._attr_unique_id = "frigate_identity_all_persons"
        self._attr_native_value: int = 0
        self._attr_extra_state_attributes: dict[str, Any] = {"persons": {}}
        self._unsub = None
        self._persons: dict[str, dict[str, Any]] = {}

    @property
    def native_value(self) -> int:
        """Return the count of tracked persons."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return self._attr_extra_state_attributes

    async def async_added_to_hass(self) -> None:
        """Subscribe to identity MQTT topics when entity is added."""

        @callback
        def _mqtt_message(msg) -> None:
            """Handle MQTT message."""
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.debug("Failed to parse MQTT payload: %s", exc)
                return

            person_id = (
                payload.get("person_id")
                or payload.get("person")
                or payload.get("name")
            )
            
            if not person_id:
                return

            # Update person data
            self._persons[person_id] = {
                "camera": payload.get("camera") or payload.get("checkpoint"),
                "confidence": payload.get("confidence"),
                "source": payload.get("source"),
                "frigate_zones": payload.get("frigate_zones", []),
                "event_id": payload.get("event_id"),
                "snapshot_url": payload.get("snapshot_url"),
                "timestamp": payload.get("timestamp"),
                "last_seen": datetime.now().isoformat(),
            }
            
            if payload.get("similarity_score") is not None:
                self._persons[person_id]["similarity_score"] = payload.get("similarity_score")

            # Update state
            self._attr_native_value = len(self._persons)
            self._attr_extra_state_attributes = {"persons": self._persons}
            self.hass, "identity/person/#", _mqtt_message
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT when entity is removed."""
        if callable(self._unsub):
            try:
                self._unsub()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Failed to unsubscribe from MQTT topic")

