"""Binary sensor platform for Ciconia - flags a tracker as stale."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_STALE_AFTER_SECONDS, DEFAULT_STALE_AFTER_SECONDS
from .coordinator import CiconiaConfigEntry, CiconiaCoordinator
from .entity import CiconiaEntity, add_entities_for_new_devices

# All data comes from the coordinator; entities never fetch on their own.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CiconiaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a "stale" binary sensor per tracker."""
    coordinator = entry.runtime_data
    add_entities_for_new_devices(
        coordinator,
        async_add_entities,
        lambda device_id: [CiconiaStaleBinarySensor(coordinator, device_id)],
    )


class CiconiaStaleBinarySensor(CiconiaEntity, BinarySensorEntity):
    """On when the tracker hasn't produced a fresh fix recently (or ever).

    The threshold is configurable in the options (stale_after_seconds) - a
    car reporting every few seconds and a battery-saving tracker that sleeps
    for hours need very different definitions of "hasn't reported in a while".
    """

    _attr_translation_key = "stale"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: CiconiaCoordinator, device_id: str) -> None:
        """Create the sensor for one tracker."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_stale"

    @property
    def is_on(self) -> bool:
        """Whether the last fix is older than the configured threshold."""
        fix_age_seconds = self.device.fix_age_seconds
        if fix_age_seconds is None:
            return True  # no fix yet at all
        threshold: int = self.coordinator.config_entry.options.get(
            CONF_STALE_AFTER_SECONDS, DEFAULT_STALE_AFTER_SECONDS
        )
        return fix_age_seconds > threshold
