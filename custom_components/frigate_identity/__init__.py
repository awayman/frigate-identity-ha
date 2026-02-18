"""Frigate Identity custom integration for Home Assistant (minimal scaffold)."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Frigate Identity integration (minimal)."""
    _LOGGER.info("Setting up Frigate Identity integration")
    return True
