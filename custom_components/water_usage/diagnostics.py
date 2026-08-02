"""Diagnostics support for Water Usage."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import WaterUsageCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: WaterUsageCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return {
        "entry": {
            k: v
            for k, v in entry.as_dict()["data"].items()
            if k not in (CONF_PASSWORD, CONF_USERNAME)
        },
        "options": dict(entry.options),
        "thresholds": coordinator.threshold_state(),
        "reading": {
            "meter_id": data.meter_id if data else None,
            "customer_id": data.customer_id if data else None,
            "location_id": data.location_id if data else None,
            "utility": data.utility if data else None,
            "usage_today": data.usage_today if data else None,
            "usage_last_hour": data.usage_last_hour if data else None,
            "usage_yesterday": data.usage_yesterday if data else None,
            "hourly_points": len(data.hourly) if data else 0,
            "daily_points": len(data.daily) if data else 0,
        },
    }
