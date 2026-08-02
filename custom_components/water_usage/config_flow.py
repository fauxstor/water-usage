"""Config flow for Water Usage (getMyMeter)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GetMyMeterClient,
    WaterUsageApiError,
    WaterUsageAuthError,
    WaterUsagePortalChangedError,
)
from .const import (
    CONF_DAILY_THRESHOLD,
    CONF_HOURLY_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_DAILY_THRESHOLD,
    DEFAULT_HOURLY_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    NAME,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional("customer_id"): str,
        vol.Optional("location_id"): str,
        vol.Optional("meter_id"): str,
    }
)


class WaterUsageConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Water Usage."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = GetMyMeterClient(
                session=session,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            client.set_ids(
                customer_id=user_input.get("customer_id") or None,
                location_id=user_input.get("location_id") or None,
                meter_id=user_input.get("meter_id") or None,
            )
            try:
                reading = await client.async_test_connection()
            except WaterUsageAuthError:
                errors["base"] = "invalid_auth"
            except WaterUsagePortalChangedError:
                errors["base"] = "portal_changed"
            except WaterUsageApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                unique = (
                    reading.meter_id
                    or user_input.get("meter_id")
                    or user_input[CONF_USERNAME]
                )
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    "meter_id": reading.meter_id or user_input.get("meter_id") or "",
                    "customer_id": reading.customer_id
                    or user_input.get("customer_id")
                    or "",
                    "account_number": reading.account_number
                    or reading.customer_id
                    or "",
                    "location_id": reading.location_id
                    or user_input.get("location_id")
                    or "",
                    "ami_channel": (reading.raw or {}).get("ami_channel", 1),
                    "utility": reading.utility,
                    "company_id": reading.company_id,
                    "customer_name": reading.customer_name,
                }
                title = reading.customer_name or reading.account_number or NAME
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> WaterUsageOptionsFlow:
        return WaterUsageOptionsFlow()


class WaterUsageOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOURLY_THRESHOLD,
                    default=opts.get(
                        CONF_HOURLY_THRESHOLD,
                        data.get(CONF_HOURLY_THRESHOLD, DEFAULT_HOURLY_THRESHOLD),
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_DAILY_THRESHOLD,
                    default=opts.get(
                        CONF_DAILY_THRESHOLD,
                        data.get(CONF_DAILY_THRESHOLD, DEFAULT_DAILY_THRESHOLD),
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(
                        CONF_SCAN_INTERVAL,
                        data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
