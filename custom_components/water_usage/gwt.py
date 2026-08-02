"""Minimal GWT-RPC request builder for the H2O Analytics portal."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GwtRequest:
    """Build a GWT-RPC body for a service method call."""

    module_base: str
    policy: str
    interface: str
    method: str
    _strings: list[str] = field(default_factory=list)
    _string_index: dict[str, int] = field(default_factory=dict)
    _body: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Header: module base + policy strong name (written into stream)
        self._body.append(str(self._add_string(self.module_base)))
        self._body.append(str(self._add_string(self.policy)))
        self._body.append(str(self._add_string(self.interface)))
        self._body.append(str(self._add_string(self.method)))

    def _add_string(self, value: str) -> int:
        if value in self._string_index:
            return self._string_index[value]
        self._strings.append(value)
        idx = len(self._strings)
        self._string_index[value] = idx
        return idx

    def write_int_literal(self, value: int) -> None:
        self._body.append(str(value))

    def write_string_type(self, type_sig: str = "java.lang.String/2004016611") -> None:
        self._body.append(str(self._add_string(type_sig)))

    def write_string_value(self, value: str) -> None:
        self._body.append(str(self._add_string(value)))

    def write_integer(self, value: int, type_sig: str = "java.lang.Integer/3438268394") -> None:
        # Object encoding: type index, then int value
        self._body.append(str(self._add_string(type_sig)))
        self._body.append(str(value))

    def build(self, version: int = 7, flags: int = 0) -> str:
        parts = [str(version), str(flags), str(len(self._strings))]
        parts.extend(self._strings)
        parts.extend(self._body)
        return "|".join(parts) + "|"


def build_login_payload(module_base: str, policy: str, username: str, password: str) -> str:
    """Build UtilityService.loginAccount(username, password)."""
    req = GwtRequest(
        module_base=module_base,
        policy=policy,
        interface="com.h2oanalytics.client.UtilityService",
        method="loginAccount",
    )
    req.write_int_literal(2)
    req.write_string_type()
    req.write_string_type()
    req.write_string_value(username)
    req.write_string_value(password)
    return req.build()


def build_noarg_payload(module_base: str, policy: str, method: str) -> str:
    """Build a zero-argument UtilityService call."""
    req = GwtRequest(
        module_base=module_base,
        policy=policy,
        interface="com.h2oanalytics.client.UtilityService",
        method=method,
    )
    req.write_int_literal(0)
    return req.build()


def build_get_main_meter_payload(
    module_base: str,
    policy: str,
    company_id: int,
    meter_id: int,
) -> str:
    """Build UtilityService.getMainMeter(Integer, Integer)."""
    req = GwtRequest(
        module_base=module_base,
        policy=policy,
        interface="com.h2oanalytics.client.UtilityService",
        method="getMainMeter",
    )
    req.write_int_literal(2)
    req.write_string_type("java.lang.Integer/3438268394")
    req.write_string_type("java.lang.Integer/3438268394")
    req.write_integer(company_id)
    req.write_integer(meter_id)
    return req.build()


def parse_gwt_response(text: str) -> tuple[str, str]:
    """Return (status, payload) where status is OK or EX."""
    if text.startswith("//OK"):
        return "OK", text[4:]
    if text.startswith("//EX"):
        return "EX", text[4:]
    return "ERR", text
