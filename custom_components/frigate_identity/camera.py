"""Camera platform for Frigate Identity.

Creates one MQTT camera entity per tracked person, subscribing to
identity/snapshots/{person_name} for cropped snapshot images.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MQTT_TOPIC_PREFIX,
    CONF_SNAPSHOT_SOURCE,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DOMAIN,
    SNAPSHOT_SOURCE_MQTT,
    TOPIC_SNAPSHOTS,
)
from .person_registry import PersonRegistry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frigate Identity camera entities."""
    config = {**config_entry.data, **config_entry.options}
    snapshot_source = config.get(CONF_SNAPSHOT_SOURCE, SNAPSHOT_SOURCE_MQTT)

    # Only create MQTT cameras for "mqtt" snapshot source
    if snapshot_source != SNAPSHOT_SOURCE_MQTT:
        _LOGGER.debug(
            "Snapshot source is '%s'; skipping MQTT camera entities", snapshot_source
        )
        return

    registry: PersonRegistry = hass.data[DOMAIN]["registry"]
    prefix = config.get(CONF_MQTT_TOPIC_PREFIX, DEFAULT_MQTT_TOPIC_PREFIX)

    tracked: dict[str, FrigateIdentityCamera] = {}

    @callback
    def _on_persons_changed() -> None:
        """Add camera entities for newly discovered persons."""
        new_entities: list[FrigateIdentityCamera] = []
        for name in registry.person_names:
            if name not in tracked:
                entity = FrigateIdentityCamera(name, prefix)
                tracked[name] = entity
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    # Register for future person discoveries
    unsub = registry.register_listener(_on_persons_changed)
    config_entry.async_on_unload(unsub)

    # Create entities for persons already known
    _on_persons_changed()


class FrigateIdentityCamera(Camera):
    """MQTT camera entity showing the latest snapshot for a person."""

    _attr_has_entity_name = True

    def __init__(self, person_name: str, topic_prefix: str) -> None:
        """Initialise the camera."""
        super().__init__()
        self._person_name = person_name
        slug = person_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_name = f"{person_name} Snapshot"
        self._attr_unique_id = f"frigate_identity_{slug}_snapshot"
        self._image: bytes | None = None
        self._topic = TOPIC_SNAPSHOTS.format(prefix=topic_prefix, name=person_name)
        self._unsub: Any = None

    @property
    def is_streaming(self) -> bool:
        """Return False — this is a snapshot camera, not a stream."""
        return False

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the latest JPEG snapshot."""
        return self._image

    async def async_added_to_hass(self) -> None:
        """Subscribe to the snapshot MQTT topic."""

        @callback
        def _message_received(msg: Any) -> None:
            """Handle incoming snapshot."""
            self._image = msg.payload
            self.async_write_ha_state()

        self._unsub = await mqtt.async_subscribe(
            self.hass, self._topic, _message_received, encoding=None
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT."""
        if callable(self._unsub):
            self._unsub()
