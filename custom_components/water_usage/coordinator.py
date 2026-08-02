"""Data update coordinator for Water Usage."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.const import UnitOfVolume
from homeassistant.util import dt as dt_util

from .api import GetMyMeterClient, MeterReading, WaterUsageApiError, WaterUsageAuthError
from .const import (
    CONF_DAILY_THRESHOLD,
    CONF_HOURLY_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_DAILY_THRESHOLD,
    DEFAULT_HOURLY_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STATISTIC_ID_PREFIX,
)

_LOGGER = logging.getLogger(__name__)


class WaterUsageCoordinator(DataUpdateCoordinator[MeterReading]):
    """Poll getMyMeter and publish sensors + external statistics."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        scan = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=int(scan)),
        )
        session = async_get_clientsession(hass)
        self.client = GetMyMeterClient(
            session=session,
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
        )
        # Optional pinned ids from options / prior discovery
        company = entry.data.get("company_id")
        self.client.set_ids(
            customer_id=entry.data.get("customer_id"),
            account_number=entry.data.get("account_number"),
            location_id=entry.data.get("location_id"),
            meter_id=entry.data.get("meter_id"),
            utility=entry.data.get("utility"),
            company_id=int(company) if company not in (None, "") else None,
        )

    @property
    def hourly_threshold(self) -> float:
        return float(
            self.entry.options.get(
                CONF_HOURLY_THRESHOLD,
                self.entry.data.get(CONF_HOURLY_THRESHOLD, DEFAULT_HOURLY_THRESHOLD),
            )
        )

    @property
    def daily_threshold(self) -> float:
        return float(
            self.entry.options.get(
                CONF_DAILY_THRESHOLD,
                self.entry.data.get(CONF_DAILY_THRESHOLD, DEFAULT_DAILY_THRESHOLD),
            )
        )

    async def _async_update_data(self) -> MeterReading:
        try:
            reading = await self.client.async_fetch_usage()
        except WaterUsageAuthError as err:
            raise UpdateFailed(str(err)) from err
        except WaterUsageApiError as err:
            raise UpdateFailed(str(err)) from err

        await self._async_import_statistics(reading)
        return reading

    async def _async_import_statistics(self, reading: MeterReading) -> None:
        """Archive usage into recorder external statistics."""
        # Prefer true hourly/daily AMI points; else monthly billing periods.
        series = reading.hourly or reading.daily or reading.monthly
        if not series:
            return

        statistic_id = f"{STATISTIC_ID_PREFIX}{reading.meter_id}"
        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"Water meter {reading.meter_id}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfVolume.GALLONS,
        )

        stats: list[StatisticData] = []
        running_sum = 0.0
        for point in series:
            running_sum += point.gallons
            start = dt_util.as_utc(point.start).replace(
                minute=0, second=0, microsecond=0
            )
            stats.append(
                StatisticData(
                    start=start,
                    sum=running_sum,
                    state=point.gallons,
                )
            )

        try:
            async_add_external_statistics(self.hass, metadata, stats)
        except Exception:  # noqa: BLE001 — recorder may be unavailable during setup
            _LOGGER.exception("Failed to import water usage statistics")

    def threshold_state(self) -> dict[str, Any]:
        """Return threshold comparison flags for binary sensors."""
        data = self.data
        if not data:
            return {"hourly_high": False, "daily_high": False}
        hourly = data.usage_last_hour
        # Daily alert: prefer true daily/today; else month-to-date daily average
        daily = data.usage_today
        if daily is None and data.usage_this_month is not None:
            daily = data.usage_this_month / max(dt_util.now().day, 1)
        # Hourly alert: prefer last hour; else estimate from daily average
        if hourly is None and daily is not None:
            hourly = daily / 24.0
        return {
            "hourly_high": hourly is not None and hourly >= self.hourly_threshold,
            "daily_high": daily is not None and daily >= self.daily_threshold,
            "hourly_threshold": self.hourly_threshold,
            "daily_threshold": self.daily_threshold,
        }
