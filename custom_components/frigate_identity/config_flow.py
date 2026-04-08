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
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_AUTO_DASHBOARD,
    CONF_DASHBOARD_NAME,
    CONF_DASHBOARD_PERSONS,
    CONF_DASHBOARD_REFRESH_TIME,
    CONF_MQTT_TOPIC_PREFIX,
    CONF_PERSON_ORDER,
    CONF_SNAPSHOT_SOURCE,
    DEFAULT_AUTO_DASHBOARD,
    DEFAULT_DASHBOARD_NAME,
    DEFAULT_DASHBOARD_PERSONS,
    DEFAULT_DASHBOARD_REFRESH_TIME,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DEFAULT_SNAPSHOT_SOURCE,
    DOMAIN,
    SNAPSHOT_SOURCES,
)
from .dashboard import async_generate_dashboard


def _slug(name: str) -> str:
    """Return a lowercase underscore slug (mirrors person_registry._slug)."""
    return name.lower().replace(" ", "_").replace("-", "_")


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

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise options flow."""
        super().__init__(config_entry)
        self._main_options: dict[str, Any] = {}
        self._person_names: list[str] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the main options, then chain to person order step."""
        if user_input is not None:
            self._main_options = user_input
            return await self.async_step_person_order()

        current = {**self.config_entry.data, **self.config_entry.options}

        # Build person list from registry for multi-select
        person_names_dict = {}
        if DOMAIN in self.hass.data and "registry" in self.hass.data[DOMAIN]:
            registry = self.hass.data[DOMAIN]["registry"]
            person_names_dict = {name: name for name in registry.person_names}

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
                    vol.Optional(
                        CONF_DASHBOARD_PERSONS,
                        default=current.get(
                            CONF_DASHBOARD_PERSONS,
                            DEFAULT_DASHBOARD_PERSONS,
                        ),
                    ): cv.multi_select(person_names_dict),
                }
            ),
        )

    async def async_step_person_order(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure display order for each known person."""
        registry = self.hass.data.get(DOMAIN, {}).get("registry")
        self._person_names = sorted(registry.person_names) if registry else []

        if user_input is not None or not self._person_names:
            # Build person_order mapping from submitted form values
            person_order: dict[str, int] = {}
            if user_input and self._person_names:
                for person_name in self._person_names:
                    key = f"order_{_slug(person_name)}"
                    if key in user_input:
                        try:
                            person_order[person_name] = int(user_input[key])
                        except (ValueError, TypeError):
                            pass

            # Preserve ordering entries for persons not shown in the current form
            existing_order: dict[str, int] = {
                **self.config_entry.data,
                **self.config_entry.options,
            }.get(CONF_PERSON_ORDER, {}) or {}
            merged_order = {**existing_order, **person_order}

            combined = {**self._main_options, CONF_PERSON_ORDER: merged_order}

            # Schedule dashboard regeneration with the new merged options
            if registry is not None:
                regen_config = {**self.config_entry.data, **combined}
                self.hass.async_create_task(
                    async_generate_dashboard(self.hass, registry, regen_config)
                )

            return self.async_create_entry(data=combined)

        # Build current order for prefilling
        current_order: dict[str, int] = {
            **self.config_entry.data,
            **self.config_entry.options,
        }.get(CONF_PERSON_ORDER, {}) or {}

        schema_dict: dict[Any, Any] = {}
        for i, person_name in enumerate(self._person_names):
            slug = _slug(person_name)
            meta_order = registry.meta.get(person_name, {}).get("order") if registry else None
            try:
                default_val = int(meta_order) if meta_order is not None else i
            except (ValueError, TypeError):
                default_val = i
            default_val = current_order.get(person_name, default_val)
            schema_dict[vol.Optional(f"order_{slug}", default=default_val)] = vol.All(
                vol.Coerce(int), vol.Range(min=0)
            )

        return self.async_show_form(
            step_id="person_order",
            data_schema=vol.Schema(schema_dict),
        )
