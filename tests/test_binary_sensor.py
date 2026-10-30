"""Tests for the Ciconia "stale" binary sensor."""

from __future__ import annotations

import copy

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ciconia.const import DOMAIN

from .conftest import SAMPLE_DEVICE_PAYLOAD, device_list


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://example.local::ac_123",
        data={"base_url": "http://example.local", "api_token": "tok", "account_id": "ac_123"},
        options=options,
    )


async def _setup(hass, aioclient_mock, entry, fix_age_seconds):
    payload = copy.deepcopy(SAMPLE_DEVICE_PAYLOAD)
    payload["device"]["fix_age_seconds"] = fix_age_seconds
    aioclient_mock.get(
        "http://example.local/api/v1/devices",
        json=device_list(("dv_8f2a1c4b9e6d", "Dad's Car", "ready")),
    )
    aioclient_mock.get(
        "http://example.local/api/v1/devices/dv_8f2a1c4b9e6d",
        json=payload,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_off_when_fresh(hass, aioclient_mock):
    entry = _entry()
    await _setup(hass, aioclient_mock, entry, fix_age_seconds=47)

    state = hass.states.get("binary_sensor.dad_s_car_stale")
    assert state.state == "off"


async def test_on_when_older_than_default_threshold(hass, aioclient_mock):
    entry = _entry()
    await _setup(hass, aioclient_mock, entry, fix_age_seconds=7200)  # 2h > default 1h

    state = hass.states.get("binary_sensor.dad_s_car_stale")
    assert state.state == "on"


async def test_on_when_never_fixed(hass, aioclient_mock):
    entry = _entry()
    await _setup(hass, aioclient_mock, entry, fix_age_seconds=None)

    state = hass.states.get("binary_sensor.dad_s_car_stale")
    assert state.state == "on"


async def test_respects_custom_threshold(hass, aioclient_mock):
    entry = _entry(stale_after_seconds=100)
    await _setup(hass, aioclient_mock, entry, fix_age_seconds=200)  # > 100s custom threshold

    state = hass.states.get("binary_sensor.dad_s_car_stale")
    assert state.state == "on"
