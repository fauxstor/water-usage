#!/usr/bin/env python3
"""Probe getMyMeter / H2O Analytics portal endpoints.

Reads credentials from ../.secrets.env (GETMYMETER_USER / GETMYMETER_PASSWORD).
Writes redacted notes under docs/probe-output/ (gitignored).

Usage:
  cp .secrets.env.example .secrets.env   # fill in credentials
  python3 scripts/probe_portal.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
import types
from pathlib import Path

try:
    import aiohttp
except ImportError:
    print("Install aiohttp first: pip install aiohttp", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "water_usage"


def _load(name: str, path: Path):
    """Load a module by file path without executing package __init__.py."""
    pkg_name = "water_usage_probe"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(COMP)]
        sys.modules[pkg_name] = pkg
    mod_name = f"{pkg_name}.{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


const = _load("const", COMP / "const.py")
gwt = _load("gwt", COMP / "gwt.py")
# api imports .const / .gwt — register aliases
sys.modules["water_usage_probe.const"] = const
sys.modules["water_usage_probe.gwt"] = gwt
# Patch relative imports by also exposing as package attrs
sys.modules["water_usage_probe"].const = const
sys.modules["water_usage_probe"].gwt = gwt

# api.py uses relative imports (from .const import ...) which need package context
api_path = COMP / "api.py"
spec = importlib.util.spec_from_file_location(
    "water_usage_probe.api",
    api_path,
    submodule_search_locations=[str(COMP)],
)
api = importlib.util.module_from_spec(spec)
api.__package__ = "water_usage_probe"
sys.modules["water_usage_probe.api"] = api
assert spec.loader is not None
spec.loader.exec_module(api)

GetMyMeterClient = api.GetMyMeterClient
WaterUsageAuthError = api.WaterUsageAuthError
WaterUsageApiError = api.WaterUsageApiError
DEFAULT_BASE_URL = const.DEFAULT_BASE_URL
GWT_PERMUTATION = const.GWT_PERMUTATION
UTILITY_POLICY = const.UTILITY_POLICY
build_login_payload = gwt.build_login_payload
build_noarg_payload = gwt.build_noarg_payload
parse_gwt_response = gwt.parse_gwt_response


def load_secrets() -> dict[str, str]:
    path = ROOT / ".secrets.env"
    if not path.exists():
        print(f"Missing {path} — copy .secrets.env.example and fill credentials.")
        sys.exit(2)
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("GETMYMETER_USER", "GETMYMETER_PASSWORD", "GETMYMETER_BASE"):
        if key in os.environ:
            env[key] = os.environ[key]
    if "GETMYMETER_USER" not in env or "GETMYMETER_PASSWORD" not in env:
        print("GETMYMETER_USER and GETMYMETER_PASSWORD required in .secrets.env")
        sys.exit(2)
    return env


def redact(text: str, secrets: dict[str, str]) -> str:
    out = text
    for key in ("GETMYMETER_PASSWORD", "GETMYMETER_USER"):
        if key in secrets and secrets[key]:
            out = out.replace(secrets[key], f"<{key}>")
    out = re.sub(r"(h2o-token=)[^;\s]+", r"\1<REDACTED>", out, flags=re.I)
    out = re.sub(r"(<token>)[^<]+(</token>)", r"\1<REDACTED>\2", out, flags=re.I)
    return out


async def main() -> None:
    secrets = load_secrets()
    base = secrets.get("GETMYMETER_BASE", DEFAULT_BASE_URL)
    out_dir = ROOT / "docs" / "probe-output"
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "base": base,
        "gwt_permutation": GWT_PERMUTATION,
        "utility_policy": UTILITY_POLICY,
        "steps": [],
    }

    async with aiohttp.ClientSession() as session:
        module = f"{base.rstrip('/')}/h2o_portal/"
        payload = build_noarg_payload(module, UTILITY_POLICY, "getPortalUtilities")
        async with session.post(
            f"{module}utilityservice",
            data=payload,
            headers={
                "Content-Type": "text/x-gwt-rpc; charset=utf-8",
                "X-GWT-Permutation": GWT_PERMUTATION,
                "X-GWT-Module-Base": module,
            },
        ) as resp:
            text = await resp.text()
            status, _ = parse_gwt_response(text)
            report["steps"].append(
                {
                    "name": "getPortalUtilities",
                    "http": resp.status,
                    "gwt": status,
                    "sample": redact(text[:400], secrets),
                }
            )
            print(f"getPortalUtilities: HTTP {resp.status} gwt={status}")

        client = GetMyMeterClient(
            session=session,
            username=secrets["GETMYMETER_USER"],
            password=secrets["GETMYMETER_PASSWORD"],
            base_url=base,
        )
        # Optional pinned ids from secrets
        client.set_ids(
            customer_id=secrets.get("GETMYMETER_CUSTOMER_ID"),
            location_id=secrets.get("GETMYMETER_LOCATION_ID"),
            meter_id=secrets.get("GETMYMETER_METER_ID"),
        )
        try:
            reading = await client.async_test_connection()
        except WaterUsageAuthError as err:
            report["steps"].append({"name": "login", "error": str(err)})
            print(f"AUTH FAILED: {err}")
            login_payload = build_login_payload(
                module,
                UTILITY_POLICY,
                secrets["GETMYMETER_USER"],
                secrets["GETMYMETER_PASSWORD"],
            )
            async with session.post(
                f"{module}utilityservice",
                data=login_payload,
                headers={
                    "Content-Type": "text/x-gwt-rpc; charset=utf-8",
                    "X-GWT-Permutation": GWT_PERMUTATION,
                    "X-GWT-Module-Base": module,
                },
            ) as resp:
                text = await resp.text()
                report["steps"].append(
                    {
                        "name": "gwt_loginAccount",
                        "http": resp.status,
                        "body": redact(text[:800], secrets),
                    }
                )
                print(f"gwt loginAccount: HTTP {resp.status}")
                print(redact(text[:300], secrets))
        except WaterUsageApiError as err:
            report["steps"].append({"name": "fetch", "error": str(err)})
            print(f"API ERROR: {err}")
        else:
            report["steps"].append(
                {
                    "name": "fetch_usage",
                    "meter_id": reading.meter_id,
                    "customer_id": reading.customer_id,
                    "location_id": reading.location_id,
                    "utility": reading.utility,
                    "usage_today": reading.usage_today,
                    "usage_last_hour": reading.usage_last_hour,
                    "usage_yesterday": reading.usage_yesterday,
                    "reading_gallons": reading.reading_gallons,
                    "hourly_points": len(reading.hourly),
                    "daily_points": len(reading.daily),
                    "hourly_tail": [
                        {"start": p.start.isoformat(), "gal": p.gallons}
                        for p in reading.hourly[-5:]
                    ],
                    "daily_tail": [
                        {"start": p.start.isoformat(), "gal": p.gallons}
                        for p in reading.daily[-5:]
                    ],
                }
            )
            print(
                f"OK meter={reading.meter_id} today={reading.usage_today} "
                f"last_hour={reading.usage_last_hour} "
                f"hourly={len(reading.hourly)} daily={len(reading.daily)}"
            )

    out_path = out_dir / "last-probe.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
