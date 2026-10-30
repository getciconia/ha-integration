"""Shared base for every Ciconia entity: one HA device per tracker."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeviceData
from .const import CONF_BASE_URL, DOMAIN, MANUFACTURER
from .coordinator import CiconiaCoordinator


class CiconiaEntity(CoordinatorEntity[CiconiaCoordinator]):
    """An entity of one tracker; unavailable while that tracker has no data."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CiconiaCoordinator, device_id: str) -> None:
        """Attach the entity to its tracker's device."""
        super().__init__(coordinator)
        self.device_id = device_id
        summary = coordinator.data.devices[device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=summary.name,
            model=summary.model,
            manufacturer=MANUFACTURER,
            configuration_url=coordinator.config_entry.data[CONF_BASE_URL],
        )

    @property
    def available(self) -> bool:
        """Unavailable while this tracker's data couldn't be fetched."""
        return super().available and self.device_id in self.coordinator.data.positions

    @property
    def device(self) -> DeviceData:
        """The tracker's latest data."""
        return self.coordinator.data.positions[self.device_id]


def add_entities_for_new_devices(
    coordinator: CiconiaCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[str], Iterable[Entity]],
) -> None:
    """Add entities for each tracked device now, and for devices that show up later.

    `build(device_id)` returns the entities for one device. Trackers added to
    the account later get their entities without a reload.
    """
    known: set[str] = set()

    def _add_new() -> None:
        # Forget removed devices so they come back if they reappear.
        known.intersection_update(coordinator.data.devices)
        new = [device_id for device_id in coordinator.data.devices if device_id not in known]
        if not new:
            return
        known.update(new)
        async_add_entities([entity for device_id in new for entity in build(device_id)])

    _add_new()
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_add_new))
