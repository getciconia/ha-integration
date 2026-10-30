"""Sensor platform for Ciconia — one entity per tracker per measurement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import DeviceData
from .coordinator import CiconiaConfigEntry, CiconiaCoordinator
from .entity import CiconiaEntity, add_entities_for_new_devices

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CiconiaSensorDescription(SensorEntityDescription):
    """A sensor and how to read its value from a tracker's data."""

    value_fn: Callable[[DeviceData], float | int | datetime | None]


def _battery_percentage(d: DeviceData) -> float | None:
    """Only real percentages: some trackers report a voltage in this field."""
    level = d.battery_level
    return level if level is not None and 0 <= level <= 100 else None


def _fixed_time(d: DeviceData) -> datetime | None:
    return dt_util.parse_datetime(d.fixed_time) if d.fixed_time else None


SENSOR_DESCRIPTIONS: tuple[CiconiaSensorDescription, ...] = (
    CiconiaSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_battery_percentage,
    ),
    CiconiaSensorDescription(
        key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.speed,
    ),
    CiconiaSensorDescription(
        key="altitude",
        translation_key="altitude",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.altitude,
    ),
    # A timestamp (not just an age) so the frontend shows a live
    # "x minutes ago" and automations can compare it directly.
    CiconiaSensorDescription(
        key="fixed_time",
        translation_key="fixed_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_fixed_time,
    ),
    CiconiaSensorDescription(
        key="fix_age_seconds",
        translation_key="fix_age",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.fix_age_seconds,
    ),
    # 0-5 bars (not dBm), so no unit; icons per level are in icons.json.
    CiconiaSensorDescription(
        key="gsm_signal",
        translation_key="gsm_signal",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.gsm_signal,
    ),
    # 0-5 like gsm_signal, computed by the server from HDOP: 5 ideal (<1),
    # 4 excellent (1-2), 3 good (2-5), 2 moderate (5-10), 1 fair (10-20),
    # 0 poor (>20) or no fix.
    CiconiaSensorDescription(
        key="gps_signal",
        translation_key="gps_signal",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.gps_signal,
    ),
    CiconiaSensorDescription(
        key="satellites",
        translation_key="satellites",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.satellites,
    ),
    CiconiaSensorDescription(
        key="chip_temperature",
        translation_key="chip_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.chip_temperature,
    ),
    CiconiaSensorDescription(
        key="hdop",
        translation_key="hdop",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.hdop,
    ),
    CiconiaSensorDescription(
        key="gsm_operator_code",
        translation_key="gsm_operator_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.gsm_operator_code,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CiconiaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of every tracker."""
    coordinator = entry.runtime_data
    add_entities_for_new_devices(
        coordinator,
        async_add_entities,
        lambda device_id: [
            CiconiaSensor(coordinator, device_id, description)
            for description in SENSOR_DESCRIPTIONS
        ],
    )


class CiconiaSensor(CiconiaEntity, SensorEntity):
    """One measurement of one tracker."""

    entity_description: CiconiaSensorDescription

    def __init__(
        self,
        coordinator: CiconiaCoordinator,
        device_id: str,
        description: CiconiaSensorDescription,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float | int | datetime | None:
        """The measurement from the latest data."""
        return self.entity_description.value_fn(self.device)
