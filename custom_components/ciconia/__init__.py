"""The Ciconia integration: GPS trackers on a Ciconia account."""

from __future__ import annotations

from homeassistant.const import CONF_API_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CiconiaApiClient
from .const import CONF_BASE_URL, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import CiconiaConfigEntry, CiconiaCoordinator

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: CiconiaConfigEntry) -> bool:
    """Set up the trackers of one Ciconia account."""
    client = CiconiaApiClient(
        async_get_clientsession(hass), entry.data[CONF_BASE_URL], entry.data[CONF_API_TOKEN]
    )
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = CiconiaCoordinator(hass, entry, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: CiconiaConfigEntry) -> None:
    """Reload the entry when its options (trackers, polling interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: CiconiaConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a tracker in HA once this entry no longer tracks it."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.data is None:
        return True
    ids = {identifier for domain, identifier in device_entry.identifiers if domain == DOMAIN}
    return not ids & set(coordinator.data.devices)


async def async_unload_entry(hass: HomeAssistant, entry: CiconiaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
