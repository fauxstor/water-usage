# Water Usage (getMyMeter) — Home Assistant

HACS custom integration that polls [getMyMeter.info](https://getmymeter.info/) (H2O Analytics customer portal), archives hourly water usage into Home Assistant statistics, and exposes threshold binary sensors for leak / high-usage alerts.

> Personal / account use only. There is no public API; this talks to the same portal endpoints as the website.

## Features

- Config-flow login with your getMyMeter username & password
- Sensors (US gallons): meter reading, today, last hour, yesterday, this/last month
- Binary sensors: hourly / daily usage above configurable thresholds
- External statistics (`water_usage:meter_*`) for Energy Dashboard archival (hourly when AMI provides it)
- Default poll interval: 30 minutes

When the portal exposes AMI hourly/daily series (`getAMIMeters` + `/ami_data`), those drive the sensors and statistics. If only monthly billing reads exist, “today” is estimated as month-to-date ÷ day-of-month.

## Install (HACS)

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/fauxstor/water-usage` as type **Integration**
3. Download **Water Usage (getMyMeter)** → restart Home Assistant
4. **Settings → Devices & services → Add integration → Water Usage**
5. Enter getMyMeter credentials
6. (Optional) Configure thresholds / poll interval under the integration **Configure** menu
7. Energy Dashboard → Water → add statistic `water_usage:meter_<id>`

## Entities

| Entity | Purpose |
|--------|---------|
| `sensor.*_usage_this_month` | Gallons in the current billing month |
| `sensor.*_usage_last_month` | Gallons last month |
| `sensor.*_usage_today` | Gallons today (AMI) or month÷day estimate |
| `sensor.*_usage_last_hour` | Last hour when AMI hourly exists |
| `sensor.*_usage_yesterday` | Yesterday when AMI daily exists |
| `sensor.*_meter_reading` | Sum of known monthly totals (proxy) |
| `binary_sensor.*_hourly_high` | Hourly (or estimated) ≥ hourly threshold |
| `binary_sensor.*_daily_high` | Daily (or estimated) ≥ daily threshold |

## Local development / API probe

```bash
cp .secrets.env.example .secrets.env   # set GETMYMETER_USER / GETMYMETER_PASSWORD
pip install aiohttp
python3 scripts/probe_portal.py
```

If the portal redeploys and GWT policy hashes change, update values in `custom_components/water_usage/const.py` using the probe output and [docs/api-notes.md](docs/api-notes.md).

## Habibi

For Home Assistant package wiring (phone alerts via `notify.habibi_phones`), see the Habibi repo doc `docs/integrations/water-usage.md`.

## License

MIT
