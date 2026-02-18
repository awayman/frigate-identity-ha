import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    """Set up the Frigate Identity sensor platform."""
    async_add_entities([FrigateIdentitySensor()])


class FrigateIdentitySensor(SensorEntity):
    """Sensor that reports the last recognized/tracked person from identity topics."""

    def __init__(self) -> None:
        self._attr_name = "Frigate Identity - Last Person"
        self._attr_unique_id = "frigate_identity_last_person"
        self._state: str | None = None
        self._attrs: dict[str, Any] = {}
        self._unsub = None

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to identity MQTT topics when entity is added."""

        @callback
        async def _mqtt_message(msg) -> None:
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception as exc:  # pragma: no cover - defensive
                _LOGGER.debug("Failed to parse MQTT payload: %s", exc)
                return

            person = payload.get("person_id") or payload.get("person") or payload.get("name")
            confidence = payload.get("confidence")
            similarity_score = payload.get("similarity_score")
            camera = payload.get("camera") or payload.get("checkpoint")
            timestamp = payload.get("timestamp")
            source = payload.get("source")

            self._state = person
            self._attrs = {
                "confidence": confidence,
                "camera": camera,
                "timestamp": timestamp,
                "source": source,
            }
            
            # Add similarity score if present (from re-id model)
            if similarity_score is not None:
                self._attrs["similarity_score"] = similarity_score
            
            self.async_write_ha_state()

        # subscribe to both recognized and tracked topics
        self._unsub = await mqtt.async_subscribe(hass, "identity/person/#", _mqtt_message)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT when entity is removed."""
        if callable(self._unsub):
            try:
                self._unsub()
            except Exception:
                _LOGGER.debug("Failed to unsubscribe from MQTT topic")
