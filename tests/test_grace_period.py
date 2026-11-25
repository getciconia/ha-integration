"""Short outages keep the last data; longer ones make entities unavailable."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.const import STATE_UNAVAILABLE

from custom_components.ciconia.const import UNAVAILABLE_AFTER

from .conftest import device_payload
from .test_account_entry import BASE, _setup, mock_account

CAR_AND_VAN = [("dv_car", "Car", "ready"), ("dv_van", "Van", "ready")]
BOTH_OK = {"dv_car": device_payload("dv_car", "Car"), "dv_van": device_payload("dv_van", "Van")}


async def _refresh(hass, coordinator, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_one_device_failing_briefly_keeps_its_data(
    hass, aioclient_mock, account_entry, freezer, caplog
):
    mock_account(aioclient_mock, CAR_AND_VAN, BOTH_OK)
    coordinator = await _setup(hass, account_entry)

    mock_account(
        aioclient_mock, CAR_AND_VAN, {"dv_car": device_payload("dv_car", "Car"), "dv_van": 502}
    )
    await _refresh(hass, coordinator, freezer, 30)

    van = hass.states.get("device_tracker.van")
    assert van.state != STATE_UNAVAILABLE
    assert van.attributes["latitude"] == 52.2296756
    assert van.attributes["fix_age_seconds"] == 47 + 30
    assert hass.states.get("sensor.van_fix_age").state == "77"
    assert "can't be fetched" not in caplog.text

    # Still failing past the grace period: only the van goes unavailable,
    # logged once.
    await _refresh(hass, coordinator, freezer, UNAVAILABLE_AFTER.total_seconds())
    await _refresh(hass, coordinator, freezer, 5)
    assert hass.states.get("device_tracker.van").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.van_altitude").state == STATE_UNAVAILABLE
    assert hass.states.get("device_tracker.car").state != STATE_UNAVAILABLE
    assert caplog.text.count("Van can't be fetched") == 1

    mock_account(aioclient_mock, CAR_AND_VAN, BOTH_OK)
    with caplog.at_level(logging.INFO):
        await _refresh(hass, coordinator, freezer, 5)
    assert hass.states.get("device_tracker.van").state != STATE_UNAVAILABLE
    assert caplog.text.count("Van can be fetched again") == 1


async def test_server_outage_keeps_data_then_goes_unavailable(
    hass, aioclient_mock, account_entry, freezer
):
    mock_account(aioclient_mock, CAR_AND_VAN, BOTH_OK)
    coordinator = await _setup(hass, account_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", status=502, json={"error": "x"})
    await _refresh(hass, coordinator, freezer, 5)
    await _refresh(hass, coordinator, freezer, 60)

    assert coordinator.last_update_success
    for entity_id in ("device_tracker.car", "device_tracker.van", "sensor.car_altitude"):
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE
    assert hass.states.get("sensor.car_fix_age").state == str(47 + 65)

    await _refresh(hass, coordinator, freezer, UNAVAILABLE_AFTER.total_seconds())
    assert not coordinator.last_update_success
    for entity_id in ("device_tracker.car", "device_tracker.van", "sensor.car_altitude"):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    mock_account(aioclient_mock, CAR_AND_VAN, BOTH_OK)
    await _refresh(hass, coordinator, freezer, 5)
    assert coordinator.last_update_success
    assert hass.states.get("device_tracker.car").state != STATE_UNAVAILABLE
    assert hass.states.get("sensor.car_fix_age").state == "47"


async def test_every_device_failing_keeps_data_while_listing_works(
    hass, aioclient_mock, account_entry, freezer
):
    mock_account(aioclient_mock, CAR_AND_VAN, BOTH_OK)
    coordinator = await _setup(hass, account_entry)

    mock_account(aioclient_mock, CAR_AND_VAN, {"dv_car": 502, "dv_van": 502})
    await _refresh(hass, coordinator, freezer, 30)
    assert hass.states.get("device_tracker.car").state != STATE_UNAVAILABLE

    await _refresh(hass, coordinator, freezer, UNAVAILABLE_AFTER.total_seconds())
    assert not coordinator.last_update_success
    assert hass.states.get("device_tracker.car").state == STATE_UNAVAILABLE


async def test_rejected_token_starts_reauth_without_waiting(
    hass, aioclient_mock, account_entry, freezer
):
    mock_account(aioclient_mock, CAR_AND_VAN, BOTH_OK)
    coordinator = await _setup(hass, account_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", status=401, json={"error": "unauthorized"})
    await _refresh(hass, coordinator, freezer, 5)

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert hass.states.get("device_tracker.car").state == STATE_UNAVAILABLE


async def test_removed_device_is_forgotten(hass, aioclient_mock, account_entry, freezer):
    mock_account(aioclient_mock, CAR_AND_VAN, BOTH_OK)
    coordinator = await _setup(hass, account_entry)

    mock_account(
        aioclient_mock, [("dv_car", "Car", "ready")], {"dv_car": device_payload("dv_car", "Car")}
    )
    await _refresh(hass, coordinator, freezer, 5)

    # The server goes down right after: the removed van doesn't come back.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", status=502, json={"error": "x"})
    await _refresh(hass, coordinator, freezer, 5)
    assert set(coordinator.data.positions) == {"dv_car"}
