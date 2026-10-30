"""Thin async client for the Ciconia API.

The api_token belongs to the account, so one client can list every device
(GET /api/v1/devices) and fetch each one's live position
(GET /api/v1/devices/{public_id}). The config flow gets that token by
linking: the user approves a short code on the Ciconia website.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT_SECONDS


class CiconiaApiError(Exception):
    """Base error for Ciconia API failures."""


class CiconiaAuthError(CiconiaApiError):
    """401 — invalid API token OR unknown public_id.

    Ciconia deliberately returns the same response for both cases
    (anti-enumeration measure on their end), so this can't distinguish
    which one is wrong — surface a single generic message covering both.
    """


class CiconiaUpstreamError(CiconiaApiError):
    """502, or any network/timeout failure. Treat as transient."""


class CiconiaLinkError(CiconiaApiError):
    """A link request ended without approval (denied, expired, unknown)."""

    def __init__(self, reason: str) -> None:
        """Remember why linking ended."""
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, kw_only=True)
class DeviceSummary:
    """One entry of GET /api/v1/devices — metadata only, no position."""

    device_id: str
    name: str
    model: str | None
    status: str  # "provisioning" or "ready"

    @property
    def ready(self) -> bool:
        """Whether the tracker is active (has finished provisioning)."""
        return self.status == "ready"

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> DeviceSummary:
        """Build from one item of the device list."""
        return cls(
            device_id=payload["device_id"],
            name=payload["name"],
            model=payload.get("model"),
            status=payload.get("status") or "ready",
        )


@dataclass(frozen=True, kw_only=True)
class DeviceData:
    """Normalized Ciconia device payload.

    Every field except device_id/name can be null — most obviously all
    together on a device with no fix yet, but individual fields can also
    be null independently depending on what the specific device/protocol
    reports. Always handle None.
    """

    device_id: str
    name: str
    model: str | None
    latitude: float | None
    longitude: float | None
    altitude: float | None
    speed: float | None
    battery_level: float | None
    gsm_signal: int | None
    gsm_operator_code: int | None
    chip_temperature: float | None
    satellites: int | None
    hdop: float | None
    gps_signal: int | None
    fixed_time: str | None
    fix_age_seconds: int | None
    attributes: dict[str, Any]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> DeviceData:
        """Build from the `device` object of a device response."""
        return cls(
            device_id=payload["device_id"],
            name=payload["name"],
            model=payload.get("model"),
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            altitude=payload.get("altitude"),
            speed=payload.get("speed"),
            battery_level=payload.get("battery_level"),
            gsm_signal=payload.get("gsm_signal"),
            gsm_operator_code=payload.get("gsm_operator_code"),
            chip_temperature=payload.get("chip_temperature"),
            satellites=payload.get("satellites"),
            hdop=payload.get("hdop"),
            gps_signal=payload.get("gps_signal"),
            fixed_time=payload.get("fixed_time"),
            fix_age_seconds=payload.get("fix_age_seconds"),
            attributes=payload.get("attributes") or {},
        )


@dataclass(frozen=True, kw_only=True)
class LinkRequest:
    """What POST /api/v1/link_requests returns — show user_code + URL."""

    user_code: str
    device_code: str
    verification_url: str
    verification_url_complete: str
    expires_in: int
    interval: int


@dataclass(frozen=True, kw_only=True)
class LinkResult:
    """An approved link request: the account's token and stable id."""

    api_token: str
    account_id: str
    account_email: str | None


async def _request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    api_token: str | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
    try:
        async with session.request(
            method,
            url,
            headers=headers,
            json=json,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
        ) as response:
            if response.status == 401:
                raise CiconiaAuthError("Invalid API token or unknown device id")
            if response.status == 502:
                raise CiconiaUpstreamError("Upstream tracking service unavailable")
            if response.status == 404:
                return 404, None
            response.raise_for_status()
            return response.status, await response.json()
    except aiohttp.ClientError as err:
        raise CiconiaUpstreamError(f"Error communicating with Ciconia: {err}") from err
    except TimeoutError as err:
        raise CiconiaUpstreamError("Timed out talking to Ciconia") from err


class CiconiaApiClient:
    """Talks to the Ciconia API with one account's token."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_token: str,
    ) -> None:
        """Use this session, server and account token."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token

    async def async_list_devices(self) -> list[DeviceSummary]:
        """Every device on the account. Cheap — no live upstream call."""
        status, payload = await _request(
            self._session, "GET", f"{self._base_url}/api/v1/devices", api_token=self._api_token
        )
        if status == 404:
            raise CiconiaUpstreamError("Device list endpoint not found")
        return [DeviceSummary.from_api(item) for item in payload["devices"]]

    async def async_get_device(self, public_id: str) -> DeviceData:
        """Fetch one device's current position/status. Raises on failure."""
        status, payload = await _request(
            self._session,
            "GET",
            f"{self._base_url}/api/v1/devices/{public_id}",
            api_token=self._api_token,
        )
        if status == 404:
            raise CiconiaAuthError("Unknown device id")
        return DeviceData.from_api(payload["device"])


async def async_create_link_request(
    session: aiohttp.ClientSession, base_url: str, client_name: str
) -> LinkRequest:
    """Ask for a code the user approves on the Ciconia website."""
    status, payload = await _request(
        session,
        "POST",
        f"{base_url.rstrip('/')}/api/v1/link_requests",
        json={"client_name": client_name},
    )
    if status == 404:
        raise CiconiaUpstreamError("This server doesn't support linking")
    return LinkRequest(
        user_code=payload["user_code"],
        device_code=payload["device_code"],
        verification_url=payload["verification_url"],
        verification_url_complete=payload["verification_url_complete"],
        expires_in=int(payload["expires_in"]),
        interval=int(payload["interval"]),
    )


async def async_poll_link_request(
    session: aiohttp.ClientSession, base_url: str, device_code: str
) -> LinkResult | None:
    """None while pending; LinkResult once approved; raises otherwise."""
    status, payload = await _request(
        session,
        "POST",
        f"{base_url.rstrip('/')}/api/v1/link_requests/poll",
        json={"device_code": device_code},
    )
    if status == 404:
        raise CiconiaLinkError("expired")
    if payload["status"] == "pending":
        return None
    if payload["status"] == "approved":
        return LinkResult(
            api_token=payload["api_token"],
            account_id=payload["account_id"],
            account_email=payload.get("account_email"),
        )
    raise CiconiaLinkError(payload["status"])
