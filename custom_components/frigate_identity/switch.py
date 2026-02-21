"""Switch platform for Frigate Identity.

Provides a manual supervision override switch that can be toggled by
notification action handlers (e.g. "Adult Present" button). Replaces
the input_boolean.manual_supervision helper that users previously had
to create manually.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frigate Identity switch entities."""
    async_add_entities([FrigateIdentityManualSupervisionSwitch()])


class FrigateIdentityManualSupervisionSwitch(SwitchEntity):
    """Manual supervision override switch.

    When turned on, supervision is considered active regardless of
    whether an adult is detected in the same zone as a child.
    Used by the notification_action_handlers blueprint.
    """

    _attr_has_entity_name = True

    def __init__(self) -> None:
        """Initialise the switch."""
        self._attr_name = "Frigate Identity Manual Supervision"
        self._attr_unique_id = "frigate_identity_manual_supervision"
        self._attr_is_on = False
        self._attr_icon = "mdi:account-supervisor"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on manual supervision."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off manual supervision."""
        self._attr_is_on = False
        self.async_write_ha_state()
