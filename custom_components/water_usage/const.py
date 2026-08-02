"""Constants for the Water Usage (getMyMeter) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "water_usage"
NAME: Final = "Water Usage"
WATER_METER_NAME: Final = "Water Meter"

CONF_HOURLY_THRESHOLD: Final = "hourly_threshold"
CONF_DAILY_THRESHOLD: Final = "daily_threshold"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_HOURLY_THRESHOLD: Final = 50.0
DEFAULT_DAILY_THRESHOLD: Final = 300.0
DEFAULT_SCAN_INTERVAL: Final = 30  # minutes
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 120

UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL)

# H2O Analytics / getMyMeter portal
DEFAULT_BASE_URL: Final = "https://h2o-analytics-hrd.appspot.com"
MODULE_PATH: Final = "/h2o_portal/"
UTILITY_SERVICE: Final = "utilityservice"

# GWT permutation + UtilityService serialization policy (desktop webkit)
# Re-probe with scripts/probe_portal.py if the portal redeploys.
GWT_PERMUTATION: Final = "085AD6A0A7FFCDCCF6CAC7CF2300A8AA"
UTILITY_POLICY: Final = "603C94AEA47F26A6709D62CA6704C05C"
USAGE_CHART_POLICY: Final = "CC17D70636E8852ABB604DF6715F491E"
TOKENCHECK_POLICY: Final = "8CE56CC8F82706CEBE2C1BEE9B3058D5"

GWT_STRING: Final = "java.lang.String/2004016611"
GWT_INTEGER: Final = "java.lang.Integer/3438268394"

ATTR_METER_ID: Final = "meter_id"
ATTR_CUSTOMER_ID: Final = "customer_id"
ATTR_LOCATION_ID: Final = "location_id"
ATTR_UTILITY: Final = "utility"

STATISTIC_ID_PREFIX: Final = f"{DOMAIN}:meter_"
