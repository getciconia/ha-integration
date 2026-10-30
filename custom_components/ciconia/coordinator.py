"""DataUpdateCoordinator for Ciconia.

No caching on Ciconia's own side at all — every device poll triggers a
live upstream call on their end. This coordinator's polling interval is the
only throttle in the whole chain, so don't poll faster than needed. A 502
is treated as transient: raise UpdateFailed and let HA's own coordinator
retry next cycle, rather than building custom retry/backoff logic on top.

Each update lists the account's devices (cheap, no upstream call) and polls
every ready one that isn't excluded, so devices added later appear on their
own and removed ones go away.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CiconiaApiClient,
    CiconiaAuthError,
    CiconiaUpstreamError,
    DeviceData,
    DeviceSummary,
)
from .const import CONF_EXCLUDED_DEVICES, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class CiconiaData:
    """Latest poll: the devices this entry tracks and their positions.

    A tracked device missing from `positions` failed this cycle (or has no
    position yet) — its entities show as unavailable.
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

    async def _async_update_data(self) -> CiconiaData:
        try:
            return await self._async_update()
        except CiconiaAuthError as err:
            # Triggers HA's reauth flow automatically — see config_flow.py.
            # Most likely cause: this Home Assistant was disconnected on the
            # Ciconia website (Integrations page), which revokes its token.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except CiconiaUpstreamError as err:
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
        positions: dict[str, DeviceData] = {}
        failures: list[BaseException] = []
        for device_id, result in zip(devices, results, strict=True):
            if isinstance(result, DeviceData):
                positions[device_id] = result
            elif isinstance(result, CiconiaAuthError):
                # The token just listed this device, so a 401 means it was
                # removed in between — not a bad token. Next cycle drops it.
                _LOGGER.debug("Device %s disappeared during the update", device_id)
            elif isinstance(result, CiconiaUpstreamError):
                failures.append(result)
            else:
                raise result

        if devices and not positions and failures:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(failures[0])},
            )

        self._remove_untracked_devices(set(devices))
        return CiconiaData(devices=devices, positions=positions)

    def _remove_untracked_devices(self, tracked: set[str]) -> None:
        """Drop HA devices this entry no longer tracks (removed or unticked)."""
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            ids = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
            if ids and not ids & tracked:
                registry.async_update_device(
                    device.id, remove_config_entry_id=self.config_entry.entry_id
                )
