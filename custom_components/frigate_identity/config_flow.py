"""Config flow for Frigate Identity integration."""
from __future__ import annotations

import os
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
    CONF_DASHBOARD_REFRESH_TIME,
    CONF_MQTT_TOPIC_PREFIX,
    CONF_PERSONS_FILE,
    CONF_SNAPSHOT_SOURCE,
    DEFAULT_AUTO_DASHBOARD,
    DEFAULT_DASHBOARD_REFRESH_TIME,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DEFAULT_PERSONS_FILE,
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
        """Handle the initial step — MQTT + persons file settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            # Validate persons file path if provided
            persons_file = user_input.get(CONF_PERSONS_FILE, "")
            if persons_file and not await self.hass.async_add_executor_job(
                os.path.isfile, persons_file
            ):
                errors[CONF_PERSONS_FILE] = "persons_file_not_found"

            if not errors:
                # Store and move to next step
                self._data = user_input
                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MQTT_TOPIC_PREFIX,
                        default=DEFAULT_MQTT_TOPIC_PREFIX,
                    ): str,
                    vol.Optional(
                        CONF_PERSONS_FILE,
                        default=DEFAULT_PERSONS_FILE,
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "default_prefix": DEFAULT_MQTT_TOPIC_PREFIX,
            },
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle snapshot source and dashboard options."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="Frigate Identity",
                data=self._data,
            )

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(
                {
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
        errors: dict[str, str] = {}

        if user_input is not None:
            persons_file = user_input.get(CONF_PERSONS_FILE, "")
            if persons_file and not await self.hass.async_add_executor_job(
                os.path.isfile, persons_file
            ):
                errors[CONF_PERSONS_FILE] = "persons_file_not_found"

            if not errors:
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
                    vol.Optional(
                        CONF_PERSONS_FILE,
                        default=current.get(
                            CONF_PERSONS_FILE, DEFAULT_PERSONS_FILE
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
                }
            ),
            errors=errors,
        )
