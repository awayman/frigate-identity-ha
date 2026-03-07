"""Config flow for Frigate Identity integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
)
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AUTO_DASHBOARD,
    CONF_DASHBOARD_NAME,
    CONF_DASHBOARD_REFRESH_TIME,
    CONF_MQTT_TOPIC_PREFIX,
    CONF_SNAPSHOT_SOURCE,
    DEFAULT_AUTO_DASHBOARD,
    DEFAULT_DASHBOARD_NAME,
    DEFAULT_DASHBOARD_REFRESH_TIME,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DEFAULT_SNAPSHOT_SOURCE,
    DOMAIN,
    SNAPSHOT_SOURCES,
)


class FrigateIdentityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Frigate Identity."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step — MQTT prefix and options."""
        if user_input is not None:
            # Prevent duplicate entries
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title="Frigate Identity",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MQTT_TOPIC_PREFIX,
                        default=DEFAULT_MQTT_TOPIC_PREFIX,
                    ): str,
                    vol.Required(
                        CONF_SNAPSHOT_SOURCE,
                        default=DEFAULT_SNAPSHOT_SOURCE,
                    ): vol.In(SNAPSHOT_SOURCES),
                    vol.Required(
                        CONF_AUTO_DASHBOARD,
                        default=DEFAULT_AUTO_DASHBOARD,
                    ): bool,
                    vol.Optional(
                        CONF_DASHBOARD_REFRESH_TIME,
                        default=DEFAULT_DASHBOARD_REFRESH_TIME,
                    ): str,
                    vol.Optional(
                        CONF_DASHBOARD_NAME,
                        default=DEFAULT_DASHBOARD_NAME,
                    ): str,
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> FrigateIdentityOptionsFlow:
        """Get the options flow for this handler."""
        return FrigateIdentityOptionsFlow(config_entry)


class FrigateIdentityOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle options flow for Frigate Identity."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MQTT_TOPIC_PREFIX,
                        default=current.get(
                            CONF_MQTT_TOPIC_PREFIX, DEFAULT_MQTT_TOPIC_PREFIX
                        ),
                    ): str,
                    vol.Required(
                        CONF_SNAPSHOT_SOURCE,
                        default=current.get(
                            CONF_SNAPSHOT_SOURCE, DEFAULT_SNAPSHOT_SOURCE
                        ),
                    ): vol.In(SNAPSHOT_SOURCES),
                    vol.Required(
                        CONF_AUTO_DASHBOARD,
                        default=current.get(
                            CONF_AUTO_DASHBOARD, DEFAULT_AUTO_DASHBOARD
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_DASHBOARD_REFRESH_TIME,
                        default=current.get(
                            CONF_DASHBOARD_REFRESH_TIME,
                            DEFAULT_DASHBOARD_REFRESH_TIME,
                        ),
                    ): str,
                    vol.Optional(
                        CONF_DASHBOARD_NAME,
                        default=current.get(
                            CONF_DASHBOARD_NAME,
                            DEFAULT_DASHBOARD_NAME,
                        ),
                    ): str,
                }
            ),
        )
