"""Sensors for Water Usage."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WATER_METER_NAME
from .coordinator import WaterUsageCoordinator

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="meter_reading",
        translation_key="meter_reading",
        name="Meter reading",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="usage_this_month",
        translation_key="usage_this_month",
        name="Usage this month",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="usage_last_month",
        translation_key="usage_last_month",
        name="Usage last month",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="usage_today",
        translation_key="usage_today",
        name="Usage today",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="usage_last_hour",
        translation_key="usage_last_hour",
        name="Usage last hour",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="usage_yesterday",
        translation_key="usage_yesterday",
        name="Usage yesterday",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: WaterUsageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WaterUsageSensor(coordinator, description) for description in SENSORS
    )


class WaterUsageSensor(CoordinatorEntity[WaterUsageCoordinator], SensorEntity):
    """Water usage sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WaterUsageCoordinator,
        description: SensorEntityDescription,
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
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data:
            return None
        return getattr(data, self.entity_description.key, None)
