# getMyMeter / H2O Analytics API notes

Personal reverse-engineering notes for https://getmymeter.info/
(backend: `https://h2o-analytics-hrd.appspot.com`).

**Do not commit credentials, cookies, or HARs with tokens.**

## Working auth flow

1. `GET /sp?action=start-session&clear=true&cls=cp`
2. `POST /sp?cls=cp&action=login&locale=en&w=1` with `username`, `password`, `device-uuid`
   - Success returns portal HTML containing `<div id="H2O-Portal-Token">…</div>`
   - Also sets `h2o-portal-token` cookie (mirror into `h2o-token`)
3. `POST /h2o_portal/tokencheck` — `TokenCheckServer(String token, Boolean)`
   - Returns `TrustedSession` with account number, utility name, meter serial, etc.
4. `POST /h2o_portal/utilityservice` — `getCustomerData(Integer companyId, String accountNumber)`
   - Returns monthly usage blob
5. `POST /h2o_portal/utilityservice` — `UsageChartService.getAMIMeters(Integer, String, String|null)`
   - Policy: UsageChart (`CC17D706…`); path is still `utilityservice`
   - Response line: `locationId|channel|meterNumber|address|flags…`
6. `GET /ami_data?cid=<company>&l=<location>&c=<channel>&b={r|d|m}&df=false&r=0`
   - Header: `H2O-Token: <token>…</token>`
   - `b=r` hourly, `b=d` daily, `b=m` monthly

`UtilityService.loginAccount` returns HTTP 500 even with valid credentials — do not use it.

## GWT constants (as of probe)

| Item | Value |
|------|-------|
| Permutation | `085AD6A0A7FFCDCCF6CAC7CF2300A8AA` |
| UtilityService policy | `603C94AEA47F26A6709D62CA6704C05C` |
| TokenCheckService policy | `8CE56CC8F82706CEBE2C1BEE9B3058D5` |
| UsageChartService policy | `CC17D70636E8852ABB604DF6715F491E` |

## getCustomerData payload

```
<ms>~Gallons~<account>*<NAME>*YYYYMM|gal|
YYYYMM|gal|
…*<email>*<phone>*…*<ADDRESS>*RESIDENTIAL*…
```

## AMI line format

`epoch_ms|period_gal|cumulative|flag`

Example (Aqua WSC): company `150`, location from `getAMIMeters` (not the company id).

## Cadence

When `getAMIMeters` + `ami_data&b=r` succeed, the integration archives true hourly intervals into external statistics and populates `usage_last_hour` / `usage_today`. Monthly billing from `getCustomerData` remains available as `usage_this_month` / `usage_last_month`.

If AMI denser series are unavailable for a utility, today is estimated as month-to-date ÷ day-of-month.

## Re-probe

```bash
cp .secrets.env.example .secrets.env
pip install aiohttp
python3 scripts/probe_portal.py
```

Update `custom_components/water_usage/const.py` if policy hashes change.
