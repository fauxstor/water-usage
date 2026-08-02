"""Async client for getMyMeter.info / H2O Analytics portal."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientSession, FormData

from .const import (
    DEFAULT_BASE_URL,
    GWT_PERMUTATION,
    MODULE_PATH,
    TOKENCHECK_POLICY,
    UTILITY_POLICY,
    UTILITY_SERVICE,
)
from .gwt import GwtRequest, build_noarg_payload, parse_gwt_response

_LOGGER = logging.getLogger(__name__)

_TOKEN_RE = re.compile(
    r'id="H2O-Portal-Token"[^>]*>([^<]+)<', re.I
)
_BOOL = "java.lang.Boolean/476441737"
_INTEGER = "java.lang.Integer/3438268394"


class WaterUsageAuthError(Exception):
    """Invalid credentials or expired session."""


class WaterUsageApiError(Exception):
    """Portal / API failure."""


class WaterUsagePortalChangedError(WaterUsageApiError):
    """GWT serialization policy or endpoint changed — re-probe required."""


@dataclass
class UsagePoint:
    """A single usage interval."""

    start: datetime
    gallons: float
    cumulative: float | None = None


@dataclass
class MeterReading:
    """Snapshot of meter state and recent usage."""

    meter_id: str
    customer_id: str
    account_number: str = ""
    location_id: str = ""
    utility: str = ""
    company_id: int | None = None
    customer_name: str = ""
    address: str = ""
    unit: str = "Gallons"
    reading_gallons: float | None = None
    usage_today: float | None = None
    usage_yesterday: float | None = None
    usage_last_hour: float | None = None
    usage_this_month: float | None = None
    usage_last_month: float | None = None
    hourly: list[UsagePoint] = field(default_factory=list)
    daily: list[UsagePoint] = field(default_factory=list)
    monthly: list[UsagePoint] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class GetMyMeterClient:
    """Talk to the H2O Analytics customer portal."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._base = base_url.rstrip("/")
        self._module_base = f"{self._base}{MODULE_PATH}"
        self._token: str | None = None
        self._company_id: int | None = None
        self._account_number: str | None = None
        self._customer_id: str | None = None
        self._location_id: str | None = None
        self._meter_id: str | None = None
        self._utility: str = ""
        self._customer_name: str = ""
        self._address: str = ""

    @property
    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._token and self._token != "null":
            headers["H2O-Token"] = f"<token>{self._token}</token>"
            headers["token"] = self._token
        return headers

    @property
    def _gwt_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "text/x-gwt-rpc; charset=utf-8",
            "X-GWT-Permutation": GWT_PERMUTATION,
            "X-GWT-Module-Base": self._module_base,
        }
        headers.update(self._auth_headers)
        return headers

    async def async_login(self) -> None:
        """Form login, then TokenCheckServer for TrustedSession."""
        await self._form_login()
        if not self._token:
            raise WaterUsageAuthError("Login succeeded but no portal token was issued")
        await self._token_check()

    async def _form_login(self) -> None:
        """POST credentials to the classic login servlet."""
        async with self._session.get(
            f"{self._base}/sp",
            params={"action": "start-session", "clear": "true", "cls": "cp", "r": "1"},
        ) as resp:
            await resp.text()

        data = FormData()
        data.add_field("username", self._username)
        data.add_field("password", self._password)
        data.add_field("device-uuid", "")

        async with self._session.post(
            f"{self._base}/sp",
            params={"cls": "cp", "action": "login", "locale": "en", "w": "1"},
            data=data,
            allow_redirects=True,
        ) as resp:
            text = await resp.text()

        if "Invalid User Name or Password" in text:
            raise WaterUsageAuthError("Invalid getMyMeter username or password")

        match = _TOKEN_RE.search(text)
        if match and match.group(1).strip() not in ("null", ""):
            self._token = match.group(1).strip()
        else:
            cookies = {c.key: c.value for c in self._session.cookie_jar}
            token = cookies.get("h2o-portal-token") or cookies.get("h2o-token")
            if token and token not in ("null", ""):
                self._token = token

        if self._token:
            self._session.cookie_jar.update_cookies({"h2o-token": self._token})

        if not self._token or 'id="login"' in text and "H2O Customer Portal" not in text:
            if "Invalid" in text or 'id="login"' in text:
                raise WaterUsageAuthError("Invalid getMyMeter username or password")

    async def _token_check(self) -> None:
        """Call TokenCheckServer — returns TrustedSession with account metadata."""
        req = GwtRequest(
            self._module_base,
            TOKENCHECK_POLICY,
            "com.h2oanalytics.client.TokenCheckService",
            "TokenCheckServer",
        )
        req.write_int_literal(2)
        req.write_string_type()
        req.write_string_type(_BOOL)
        req.write_string_value(self._token or "")
        type_idx = req._add_string(_BOOL)
        req._body.append(str(type_idx))
        req._body.append("1")  # Boolean true

        text = await self._gwt_post(req.build(), service="tokencheck")
        status, body = parse_gwt_response(text)
        if status != "OK":
            raise WaterUsageApiError(f"TokenCheckServer failed: {text[:200]}")

        strings = re.findall(r'"((?:\\.|[^"\\])*)"', body)
        self._parse_trusted_session(strings, body)

    def _parse_trusted_session(self, strings: list[str], body: str) -> None:
        """Extract company id, account number, utility, meter from TrustedSession."""
        for s in strings:
            if "Water" in s and "Corporation" in s or s.endswith("WSC") or "Utility" in s:
                if not self._utility and "maptile" not in s:
                    self._utility = s
            if re.fullmatch(r"\d{6,12}", s) and not self._account_number:
                # Account numbers like 0401893001
                self._account_number = s
                self._customer_id = s
            if re.fullmatch(r"\d{13,20}", s) and not self._meter_id:
                # Long AMI / serial ids (avoid treating account as meter)
                self._meter_id = s

        # Company / utility numeric id — Integer values in the stream (e.g. 150)
        # Prefer values that later work with getCustomerData.
        int_candidates = [
            int(n)
            for n in re.findall(r"(?<![.\d])(\d{2,4})(?![.\d])", body.split("[")[0])
            if 1 <= int(n) <= 9999
        ]
        # Also scan near known pattern: typeIndex for Integer followed by value
        # Fallback: common Aqua WSC id discovered via probe
        if not self._company_id:
            for cand in (150, *int_candidates):
                self._company_id = cand
                break

        for s in strings:
            if "@" in s and "h2oanalytics" not in s and "," not in s:
                # customer email sometimes present
                pass
            if re.search(r"\b(TX|OK|TN|FL)\b", s) and any(
                ch.isdigit() for ch in s
            ):
                if "Hwy" in s or "Drawer" in s:
                    continue  # utility mailing address
                if not self._address and len(s) < 80:
                    self._address = s

        if strings:
            # Customer display name is often an early non-type string
            for s in strings:
                if (
                    s
                    and not s.startswith("java.")
                    and not s.startswith("com.")
                    and "Water" not in s
                    and "@" not in s
                    and not s.startswith("/")
                    and not re.fullmatch(r"[\d.\-]+", s)
                    and " " in s
                    and len(s) < 80
                ):
                    self._customer_name = s
                    break

        if self._utility == "" and strings:
            for s in strings:
                if "Water" in s and "maptile" not in s:
                    self._utility = s.split("|")[0]
                    break

    async def _gwt_post(self, payload: str, service: str = UTILITY_SERVICE) -> str:
        url = urljoin(self._module_base, service)
        try:
            async with self._session.post(
                url, data=payload, headers=self._gwt_headers
            ) as resp:
                text = await resp.text()
                if resp.status == 404:
                    raise WaterUsagePortalChangedError(
                        f"{service} endpoint missing — portal may have changed; "
                        "re-run scripts/probe_portal.py"
                    )
                if resp.status >= 400 and not text.startswith("//"):
                    raise WaterUsageApiError(
                        f"GWT HTTP {resp.status}: {text[:200]}"
                    )
                return text
        except ClientError as err:
            raise WaterUsageApiError(f"Network error talking to portal: {err}") from err

    async def async_fetch_usage(self) -> MeterReading:
        """Fetch latest usage (monthly series + derived sensors)."""
        if not self._token:
            await self.async_login()

        monthly: list[UsagePoint] = []
        daily: list[UsagePoint] = []
        unit = "Gallons"
        name = self._customer_name
        address = self._address

        # Resolve company id if needed by probing getCustomerData
        company_ids: list[int] = []
        for cand in (self._company_id, 150, 1):
            if cand is not None and cand not in company_ids:
                company_ids.append(cand)

        account = self._account_number or self._customer_id
        if not account:
            raise WaterUsageApiError(
                "Could not discover account number from TrustedSession"
            )

        def _looks_like_usage(blob: str) -> bool:
            # Real payloads embed YYYYMM|gallons| rows; misses look like ****null*Not found*
            return bool(re.search(r"\d{6}\|\d", blob)) and "****null*Not found*" not in blob

        raw_customer = ""
        for company in company_ids:
            raw_customer = await self._get_customer_data(company, account)
            if raw_customer and _looks_like_usage(raw_customer):
                self._company_id = company
                break
        else:
            # retry login once
            await self.async_login()
            account = self._account_number or account
            for company in company_ids:
                raw_customer = await self._get_customer_data(company, account)
                if raw_customer and _looks_like_usage(raw_customer):
                    self._company_id = company
                    break

        if not raw_customer or not _looks_like_usage(raw_customer):
            raise WaterUsageApiError("getCustomerData returned no usage for account")

        monthly, meta = self._parse_customer_data(raw_customer)
        unit = meta.get("unit", unit)
        name = meta.get("name") or name
        address = meta.get("address") or address
        if meta.get("account"):
            self._account_number = meta["account"]
            self._customer_id = meta["account"]

        # Optional denser AMI daily series when location is known/configured
        if self._location_id and self._company_id:
            daily = await self._fetch_ami_series(
                company_id=self._company_id,
                location_id=int(self._location_id),
                channel=int(self._meter_id or 1)
                if (self._meter_id or "1").isdigit() and len(self._meter_id or "") < 6
                else 1,
                bucket="d",
            ) or []

        usage_this_month = monthly[-1].gallons if monthly else None
        usage_last_month = monthly[-2].gallons if len(monthly) >= 2 else None

        usage_today = None
        usage_yesterday = None
        usage_last_hour = None
        if daily:
            usage_today = self._sum_for_local_day(daily, 0)
            usage_yesterday = self._sum_for_local_day(daily, 1)
            # Approximate "last hour" unavailable — leave None
        elif usage_this_month is not None:
            # Estimate daily average for threshold helpers when only monthly exists
            now = datetime.now().astimezone()
            day = max(now.day, 1)
            usage_today = round(usage_this_month / day, 2)

        reading = None
        if monthly:
            # Running sum of monthly usage as a soft cumulative proxy
            reading = round(sum(p.gallons for p in monthly), 2)

        meter_id = self._meter_id or self._account_number or "unknown"
        return MeterReading(
            meter_id=str(meter_id),
            customer_id=str(self._customer_id or account),
            account_number=str(self._account_number or account),
            location_id=str(self._location_id or ""),
            utility=self._utility,
            company_id=self._company_id,
            customer_name=name or self._customer_name,
            address=address or self._address,
            unit=unit,
            reading_gallons=reading,
            usage_today=usage_today,
            usage_yesterday=usage_yesterday,
            usage_last_hour=usage_last_hour,
            usage_this_month=usage_this_month,
            usage_last_month=usage_last_month,
            hourly=[],
            daily=daily,
            monthly=monthly,
            raw={"customer_blob_len": len(raw_customer)},
        )

    async def _get_customer_data(self, company_id: int, account: str) -> str:
        req = GwtRequest(
            self._module_base,
            UTILITY_POLICY,
            "com.h2oanalytics.client.UtilityService",
            "getCustomerData",
        )
        req.write_int_literal(2)
        req.write_string_type(_INTEGER)
        req.write_string_type()
        req.write_integer(company_id)
        req.write_string_value(account)
        text = await self._gwt_post(req.build())
        status, body = parse_gwt_response(text)
        if status != "OK":
            _LOGGER.debug("getCustomerData failed for %s/%s: %s", company_id, account, text[:120])
            return ""
        strings = re.findall(r'"((?:\\.|[^"\\])*)"', body)
        if not strings:
            return ""
        raw = strings[0]
        try:
            return bytes(raw, "utf-8").decode("unicode_escape")
        except Exception:  # noqa: BLE001
            return raw.replace("\\n", "\n").replace("\\u003C", "<")

    @staticmethod
    def _parse_customer_data(raw: str) -> tuple[list[UsagePoint], dict[str, str]]:
        """Parse getCustomerData payload.

        Shape:
        ``<ms>~Gallons~<account>*<NAME>*YYYYMM|gal|\\nYYYYMM|gal|...*email*...*ADDRESS*...``
        """
        meta: dict[str, str] = {}
        monthly: list[UsagePoint] = []

        # Split header ~ units ~ body
        parts = raw.split("~", 2)
        if len(parts) >= 2:
            meta["unit"] = parts[1] if parts[1] else "Gallons"
        body = parts[2] if len(parts) >= 3 else raw

        # account*NAME*months*trailing
        # months section starts at first YYYYMM|
        m = re.search(r"^([^*]+)\*([^*]*)\*(.*)$", body, re.S)
        if not m:
            return monthly, meta
        meta["account"] = m.group(1)
        meta["name"] = m.group(2)
        rest = m.group(3)

        # Trailing metadata after last month line often starts with *
        month_blob, _, trailer = rest.partition("*")
        if trailer:
            fields = trailer.split("*")
            # email, phone, ?, address, class, ...
            for field in fields:
                if re.search(r"\d+.*(RD|ST|AVE|LN|DR|HWY|BLVD)", field, re.I):
                    meta["address"] = field
                    break
                if "RESIDENTIAL" in field.upper() or "COMMERCIAL" in field.upper():
                    continue

        for line in month_blob.splitlines():
            line = line.strip().strip("|")
            if not line or "|" not in line:
                continue
            ym, gal_s, *_ = line.split("|")
            ym = ym.strip()
            if not re.fullmatch(r"\d{6}", ym):
                continue
            try:
                gallons = float(gal_s)
                year = int(ym[:4])
                month = int(ym[4:6])
                start = datetime(year, month, 1, tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            monthly.append(UsagePoint(start=start, gallons=gallons))

        monthly.sort(key=lambda p: p.start)
        return monthly, meta

    async def _fetch_ami_series(
        self,
        company_id: int,
        location_id: int,
        channel: int,
        bucket: str,
    ) -> list[UsagePoint] | None:
        url = (
            f"{self._base}/ami_data"
            f"?cid={company_id}&l={location_id}&c={channel}"
            f"&b={bucket}&df=false&r=0"
        )
        try:
            async with self._session.get(url, headers=self._auth_headers) as resp:
                text = await resp.text()
                if resp.status != 200 or text.startswith("<html"):
                    return None
                return self._parse_ami_text(text)
        except ClientError as err:
            _LOGGER.warning("ami_data network error: %s", err)
            return None

    @staticmethod
    def _parse_ami_text(text: str) -> list[UsagePoint]:
        """Parse ``epoch_ms|period_gal|cumulative|flag`` lines."""
        points: list[UsagePoint] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("<") or "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            try:
                ts_ms = int(float(parts[0]))
                gallons = float(parts[1])
                cumulative = float(parts[2]) if len(parts) > 2 and parts[2] else None
            except (TypeError, ValueError):
                continue
            if ts_ms < 1_000_000_000_000:
                ts_ms *= 1000
            start = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            points.append(
                UsagePoint(start=start, gallons=gallons, cumulative=cumulative)
            )
        points.sort(key=lambda p: p.start)
        return points

    @staticmethod
    def _sum_for_local_day(points: list[UsagePoint], days_ago: int) -> float | None:
        if not points:
            return None
        now = datetime.now().astimezone()
        target = (now - timedelta(days=days_ago)).date()
        total = 0.0
        found = False
        for p in points:
            local = p.start.astimezone(now.tzinfo)
            if local.date() == target:
                total += p.gallons
                found = True
        return total if found else None

    async def async_test_connection(self) -> MeterReading:
        """Login and fetch once — used by config flow."""
        await self.async_login()
        payload = build_noarg_payload(
            self._module_base, UTILITY_POLICY, "getPortalUtilities"
        )
        text = await self._gwt_post(payload)
        status, _ = parse_gwt_response(text)
        if status != "OK":
            raise WaterUsagePortalChangedError(
                "getPortalUtilities failed — GWT policy may have changed; "
                "re-run scripts/probe_portal.py"
            )
        return await self.async_fetch_usage()

    def set_ids(
        self,
        *,
        customer_id: str | None = None,
        location_id: str | None = None,
        meter_id: str | None = None,
        utility: str | None = None,
        company_id: int | None = None,
        account_number: str | None = None,
    ) -> None:
        """Allow config entry / probe to pin known identifiers."""
        if customer_id:
            self._customer_id = customer_id
            if not self._account_number:
                self._account_number = customer_id
        if account_number:
            self._account_number = account_number
            self._customer_id = account_number
        if location_id:
            self._location_id = location_id
        if meter_id:
            self._meter_id = meter_id
        if utility:
            self._utility = utility
        if company_id is not None:
            self._company_id = company_id
