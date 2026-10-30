"""Device tracker platform for Ciconia - one GPS entity per tracker."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CiconiaConfigEntry, CiconiaCoordinator
from .entity import CiconiaEntity, add_entities_for_new_devices

PARALLEL_UPDATES = 0

# Typical GPS user range error in metres; accuracy ≈ HDOP x this. Lets HA's
# zone logic ignore positions that are too vague to trust.
GPS_UERE_METERS = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CiconiaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a device tracker per tracker."""
    coordinator = entry.runtime_data
    add_entities_for_new_devices(
        coordinator,
        async_add_entities,
        lambda device_id: [CiconiaDeviceTracker(coordinator, device_id)],
    )


class CiconiaDeviceTracker(CiconiaEntity, TrackerEntity):
    """GPS location entity for one Ciconia tracker."""

    _attr_name = None  # the device's own name, no suffix
    _attr_translation_key = "location"
    # Home Assistant files device trackers under "Diagnostic" by default
    # (made for routers seeing phones); here the location is the main thing.
    _attr_entity_category = None  # type: ignore[assignment]  # narrowed to non-None upstream

    def __init__(self, coordinator: CiconiaCoordinator, device_id: str) -> None:
        """Create the tracker entity."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_location"

    @property
    def source_type(self) -> SourceType:
        """GPS-based."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Latitude of the last fix."""
        return self.device.latitude

    @property
    def longitude(self) -> float | None:
        """Longitude of the last fix."""
        return self.device.longitude

    @property
    def location_accuracy(self) -> float:
        """Estimated accuracy in metres (HDOP x typical range error), 0 if unknown."""
        hdop = self.device.hdop
        return round(hdop * GPS_UERE_METERS) if hdop else 0

    @property
    def battery_level(self) -> int | None:
        """Battery as a 0-100 percentage, when the tracker reports one.

        Some trackers report a voltage in the same field; anything outside
        0-100 is not a percentage and is left out.
        """
        level = self.device.battery_level
        if level is None or not 0 <= level <= 100:
            return None
        return round(level)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """When the fix was taken - HA's own timestamps are the poll time."""
        device = self.device
        return {
            "altitude": device.altitude,
            "speed": device.speed,
            "fixed_time": device.fixed_time,
            "fix_age_seconds": device.fix_age_seconds,
        }
