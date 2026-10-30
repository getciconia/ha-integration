"""Diagnostics for Ciconia: what the integration sees, minus secrets and positions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant

from .const import CONF_ACCOUNT_EMAIL
from .coordinator import CiconiaConfigEntry

# Positions say where someone lives; raw attributes can carry the same.
TO_REDACT = {
    CONF_API_TOKEN,
    CONF_ACCOUNT_EMAIL,
    "latitude",
    "longitude",
    "altitude",
    "attributes",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CiconiaConfigEntry
) -> dict[str, Any]:
    """Return redacted entry settings and the latest poll."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return async_redact_data(
        {
            "entry": {
                "title": "**REDACTED**",
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "coordinator": {
                "last_update_success": coordinator.last_update_success,
                "update_interval_seconds": (
                    coordinator.update_interval.total_seconds()
                    if coordinator.update_interval
                    else None
                ),
            },
            "devices": {device_id: asdict(summary) for device_id, summary in data.devices.items()}
            if data
            else {},
            "positions": {
                device_id: asdict(position) for device_id, position in data.positions.items()
            }
            if data
            else {},
        },
        TO_REDACT,
    )
