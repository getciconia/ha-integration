"""DataUpdateCoordinator for Ciconia.

No caching on Ciconia's own side at all - every device poll triggers a
live upstream call on their end. This coordinator's polling interval is the
only throttle in the whole chain, so don't poll faster than needed. A 502
is treated as transient: HA's own coordinator retries next cycle, no custom
retry/backoff logic on top.

A tracker that can't be fetched keeps its last data (with its fix age moved
on) for UNAVAILABLE_AFTER, so a blip doesn't flip its entities to
unavailable and back every cycle. Past that it is left out (unavailable,
logged once); if no tracker can be fetched any more, UpdateFailed lets HA
mark everything unavailable and log it once. Auth failures never wait.

Each update lists the account's devices (cheap, no upstream call) and polls
every ready one that isn't excluded, so devices added later appear on their
own and removed ones go away.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    CiconiaApiClient,
    CiconiaAuthError,
    CiconiaUpstreamError,
    DeviceData,
    DeviceSummary,
)
from .const import CONF_EXCLUDED_DEVICES, DOMAIN, UNAVAILABLE_AFTER

_LOGGER = logging.getLogger(__name__)


@dataclass
class CiconiaData:
    """Latest poll: the devices this entry tracks and their positions.

    A tracked device missing from `positions` couldn't be fetched for longer
    than UNAVAILABLE_AFTER (or has no data yet) - its entities show as
    unavailable. A position can be one reused from an earlier cycle.
    """

    devices: dict[str, DeviceSummary] = field(default_factory=dict)
    positions: dict[str, DeviceData] = field(default_factory=dict)


type CiconiaConfigEntry = ConfigEntry[CiconiaCoordinator]


class CiconiaCoordinator(DataUpdateCoordinator[CiconiaData]):
    """Polls every device a config entry tracks on an interval."""

    config_entry: CiconiaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CiconiaConfigEntry,
        client: CiconiaApiClient,
        scan_interval: int,
    ) -> None:
        """Poll with `client` every `scan_interval` seconds."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        # Each device's last successfully fetched data, and when.
        self._last_good: dict[str, tuple[DeviceData, datetime]] = {}
        # Devices logged as unavailable, to log their recovery once.
        self._unavailable: set[str] = set()

    async def _async_update_data(self) -> CiconiaData:
        try:
            return await self._async_update()
        except CiconiaAuthError as err:
            # Triggers HA's reauth flow automatically - see config_flow.py.
            # Most likely cause: this Home Assistant was disconnected on the
            # Ciconia website (Integrations page), which revokes its token.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except CiconiaUpstreamError as err:
            if (held := self._hold_last_data()) is not None:
                _LOGGER.debug("Update failed, keeping the last data for now: %s", err)
                return held
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_update(self) -> CiconiaData:
        listed = await self.client.async_list_devices()
        skip = set(self.config_entry.options.get(CONF_EXCLUDED_DEVICES, []))
        # Provisioning devices have no position yet; they join once active.
        devices = {d.device_id: d for d in listed if d.ready and d.device_id not in skip}

        results = await asyncio.gather(
            *(self.client.async_get_device(device_id) for device_id in devices),
            return_exceptions=True,
        )
        now = dt_util.utcnow()
        positions: dict[str, DeviceData] = {}
        failures: list[BaseException] = []
        gone_unavailable: list[str] = []
        for device_id, result in zip(devices, results, strict=True):
            if isinstance(result, DeviceData):
                positions[device_id] = result
                self._last_good[device_id] = (result, now)
                if device_id in self._unavailable:
                    self._unavailable.discard(device_id)
                    _LOGGER.info("%s can be fetched again", devices[device_id].name)
            elif isinstance(result, CiconiaAuthError):
                # The token just listed this device, so a 401 means it was
                # removed in between - not a bad token. Next cycle drops it.
                _LOGGER.debug("Device %s disappeared during the update", device_id)
            elif isinstance(result, CiconiaUpstreamError):
                failures.append(result)
                if (held := self._reuse(device_id, now)) is not None:
                    positions[device_id] = held
                elif device_id not in self._unavailable:
                    gone_unavailable.append(device_id)
            else:
                raise result

        if devices and not positions and failures:
            raise failures[0]  # nothing to show: unavailable as a whole, logged by HA

        for device_id in gone_unavailable:
            self._unavailable.add(device_id)
            _LOGGER.warning("%s can't be fetched", devices[device_id].name)

        for device_id in set(self._last_good) - set(devices):
            del self._last_good[device_id]
        self._unavailable &= set(devices)
        self._remove_untracked_devices(set(devices))
        self._follow_renames(devices)
        return CiconiaData(devices=devices, positions=positions)

    def _reuse(self, device_id: str, now: datetime) -> DeviceData | None:
        """The device's last good data, if recent enough, its fix age moved on."""
        if (last := self._last_good.get(device_id)) is None:
            return None
        data, fetched_at = last
        elapsed = now - fetched_at
        if elapsed >= UNAVAILABLE_AFTER:
            return None
        if data.fix_age_seconds is None:
            return data
        return replace(data, fix_age_seconds=data.fix_age_seconds + int(elapsed.total_seconds()))

    def _hold_last_data(self) -> CiconiaData | None:
        """The previous cycle again when nothing could be fetched, while recent."""
        previous: CiconiaData | None = self.data  # None before the first refresh
        if previous is None:
            return None
        now = dt_util.utcnow()
        positions = {
            device_id: held
            for device_id in previous.devices
            if (held := self._reuse(device_id, now)) is not None
        }
        if not positions:
            return None
        return CiconiaData(devices=previous.devices, positions=positions)

    def _follow_renames(self, devices: dict[str, DeviceSummary]) -> None:
        """Rename HA devices renamed in Ciconia (a name set in HA still wins)."""
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            for domain, device_id in device.identifiers:
                summary = devices.get(device_id) if domain == DOMAIN else None
                if summary and device.name != summary.name:
                    registry.async_update_device(device.id, name=summary.name)

    def _remove_untracked_devices(self, tracked: set[str]) -> None:
        """Drop HA devices this entry no longer tracks (removed or unticked)."""
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            ids = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
            if ids and not ids & tracked:
                registry.async_update_device(
                    device.id, remove_config_entry_id=self.config_entry.entry_id
                )
