"""Binary sensors for usage threshold alerts."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WATER_METER_NAME
from .coordinator import WaterUsageCoordinator

BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="hourly_high",
        translation_key="hourly_high",
        name="Hourly usage high",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    BinarySensorEntityDescription(
        key="daily_high",
        translation_key="daily_high",
        name="Daily usage high",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: WaterUsageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WaterUsageBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class WaterUsageBinarySensor(
    CoordinatorEntity[WaterUsageCoordinator], BinarySensorEntity
):
    """Threshold binary sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WaterUsageCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        meter_id = (
            (coordinator.data.meter_id if coordinator.data else None)
            or coordinator.entry.data.get("meter_id")
            or coordinator.entry.entry_id
        )
        self._attr_unique_id = f"{meter_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(meter_id))},
            name=f"{WATER_METER_NAME} {meter_id}",
            manufacturer="getMyMeter / H2O Analytics",
            model="AMI water meter",
        )

    @property
    def is_on(self) -> bool:
        flags = self.coordinator.threshold_state()
        return bool(flags.get(self.entity_description.key, False))

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        flags = self.coordinator.threshold_state()
        return {
            "hourly_threshold": flags.get("hourly_threshold", 0),
            "daily_threshold": flags.get("daily_threshold", 0),
        }
