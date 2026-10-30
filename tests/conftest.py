"""Shared fixtures for Ciconia tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ciconia.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make custom_components importable in every test (standard HA test fixture)."""
    yield


@pytest.fixture
def account_entry() -> MockConfigEntry:
    """An account-wide entry, as created by linking."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://example.local::ac_123",
        title="adam@example.com",
        data={
            "base_url": "http://example.local",
            "api_token": "tok",
            "account_id": "ac_123",
            "account_email": "adam@example.com",
        },
        options={"excluded_devices": []},
    )


def device_list(*devices: tuple[str, str, str]) -> dict:
    """GET /api/v1/devices payload from (device_id, name, status) tuples."""
    return {
        "devices": [
            {"device_id": device_id, "name": name, "model": "Basic", "status": status}
            for device_id, name, status in devices
        ]
    }


def device_payload(device_id: str, name: str, **fields) -> dict:
    """GET /api/v1/devices/{id} payload based on SAMPLE_DEVICE_PAYLOAD."""
    return {
        "device": {
            **SAMPLE_DEVICE_PAYLOAD["device"],
            "device_id": device_id,
            "name": name,
            **fields,
        }
    }


SAMPLE_DEVICE_PAYLOAD = {
    "device": {
        "device_id": "dv_8f2a1c4b9e6d",
        "name": "Dad's Car",
        "model": "Basic",
        "latitude": 52.2296756,
        "longitude": 21.0122287,
        "altitude": 112.3,
        "speed": 42.5,
        "battery_level": 87,
        "gsm_signal": 4,
        "gsm_operator_code": 26001,
        "chip_temperature": 23.2,
        "satellites": 9,
        "hdop": 1.2,
        "gps_signal": 4,
        "fixed_time": "2026-08-18T14:32:07Z",
        "fix_age_seconds": 47,
        "attributes": {"odometer": 126092},
    }
}
