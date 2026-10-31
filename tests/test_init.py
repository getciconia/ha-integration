"""Setup, unload, entities and diagnostics of a linked account."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.ciconia.const import DOMAIN
from custom_components.ciconia.diagnostics import async_get_config_entry_diagnostics

from .conftest import SAMPLE_DEVICE_PAYLOAD, device_list, device_payload

BASE = "http://example.local"
CAR = "dv_8f2a1c4b9e6d"


def mock_car(aioclient_mock, **fields):
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", json=device_list((CAR, "Dad's Car", "ready")))
    aioclient_mock.get(
        f"{BASE}/api/v1/devices/{CAR}", json=device_payload(CAR, "Dad's Car", **fields)
    )


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_device_tracker_and_sensors(hass, aioclient_mock, account_entry):
    aioclient_mock.get(f"{BASE}/api/v1/devices", json=device_list((CAR, "Dad's Car", "ready")))
    aioclient_mock.get(f"{BASE}/api/v1/devices/{CAR}", json=SAMPLE_DEVICE_PAYLOAD)

    await _setup(hass, account_entry)

    assert account_entry.state is ConfigEntryState.LOADED
    coordinator = account_entry.runtime_data
    assert list(coordinator.data.positions) == [CAR]

    assert hass.states.get("sensor.dad_s_car_last_fix").state == "2026-08-18T14:32:07+00:00"
    assert hass.states.get("sensor.dad_s_car_battery").state == "87"
    assert hass.states.get("sensor.dad_s_car_speed").state == "42.5"
    assert hass.states.get("sensor.dad_s_car_altitude").state == "112.3"
    assert hass.states.get("sensor.dad_s_car_fix_age").state == "47"
    assert hass.states.get("sensor.dad_s_car_gsm_signal").state == "4"
    assert hass.states.get("sensor.dad_s_car_gps_signal").state == "4"
    assert hass.states.get("sensor.dad_s_car_visible_satellites").state == "9"
    assert hass.states.get("sensor.dad_s_car_chip_temperature").state == "23.2"
    # Disabled by default: registered, but no state.
    registry = er.async_get(hass)
    assert (
        registry.async_get("sensor.dad_s_car_hdop").disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )
    assert hass.states.get("sensor.dad_s_car_hdop") is None
    assert hass.states.get("sensor.dad_s_car_gsm_operator_code") is None

    tracker = hass.states.get("device_tracker.dad_s_car")
    assert tracker.state == "not_home"
    assert tracker.attributes["latitude"] == 52.2296756
    assert tracker.attributes["gps_accuracy"] == 6  # HDOP 1.2 x 5 m
    assert tracker.attributes["battery_level"] == 87
    assert tracker.attributes["fix_age_seconds"] == 47
    assert tracker.attributes["source_type"] == "gps"
    # The location is the device's main entity, not a diagnostic one.
    assert registry.async_get("device_tracker.dad_s_car").entity_category is None

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, CAR), account_entry.entry_id
    )
    assert device.name == "Dad's Car"
    assert device.manufacturer == "Ciconia"
    assert device.model == "Basic"
    assert device.configuration_url == BASE


async def test_voltage_and_missing_values(hass, aioclient_mock, account_entry):
    """A voltage in battery_level isn't a percentage; missing fields stay unknown."""
    mock_car(aioclient_mock, battery_level=12.6 * 10, hdop=None, fixed_time=None, speed=None)

    await _setup(hass, account_entry)

    assert hass.states.get("sensor.dad_s_car_battery").state == STATE_UNKNOWN
    assert hass.states.get("sensor.dad_s_car_last_fix").state == STATE_UNKNOWN
    assert hass.states.get("sensor.dad_s_car_speed").state == STATE_UNKNOWN
    tracker = hass.states.get("device_tracker.dad_s_car")
    assert tracker.attributes["gps_accuracy"] == 0
    assert "battery_level" not in tracker.attributes


async def test_setup_retries_when_the_server_is_unreachable(hass, aioclient_mock, account_entry):
    aioclient_mock.get(f"{BASE}/api/v1/devices", exc=TimeoutError)
    account_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass, aioclient_mock, account_entry):
    mock_car(aioclient_mock)
    await _setup(hass, account_entry)

    assert await hass.config_entries.async_unload(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.NOT_LOADED


async def test_remove_device_only_once_untracked(
    hass, aioclient_mock, account_entry, hass_ws_client
):
    assert await async_setup_component(hass, "config", {})
    mock_car(aioclient_mock)
    await _setup(hass, account_entry)
    registry = dr.async_get(hass)
    car = registry.async_get_device_by_identifier((DOMAIN, CAR), account_entry.entry_id)
    stray = registry.async_get_or_create(
        config_entry_id=account_entry.entry_id, identifiers={(DOMAIN, "dv_gone")}
    )
    client = await hass_ws_client(hass)

    async def remove(device_id: str) -> bool:
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove_config_entry",
                "config_entry_id": account_entry.entry_id,
                "device_id": device_id,
            }
        )
        return (await client.receive_json())["success"]

    assert not await remove(car.id)
    assert await remove(stray.id)


async def test_options_flow_aborts_when_the_token_is_rejected(hass, aioclient_mock, account_entry):
    mock_car(aioclient_mock)
    await _setup(hass, account_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", status=401, json={"error": "x"})
    result = await hass.config_entries.options.async_init(account_entry.entry_id)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


async def test_options_flow_aborts_when_offline(hass, aioclient_mock, account_entry):
    mock_car(aioclient_mock)
    await _setup(hass, account_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", exc=TimeoutError)
    result = await hass.config_entries.options.async_init(account_entry.entry_id)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_diagnostics_redact_secrets_and_positions(hass, aioclient_mock, account_entry):
    mock_car(aioclient_mock)
    await _setup(hass, account_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, account_entry)

    assert diagnostics["entry"]["data"]["api_token"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["account_email"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["base_url"] == BASE
    position = diagnostics["positions"][CAR]
    assert position["latitude"] == "**REDACTED**"
    assert position["longitude"] == "**REDACTED**"
    assert position["attributes"] == "**REDACTED**"
    assert position["gsm_signal"] == 4
    assert diagnostics["devices"][CAR]["status"] == "ready"
    assert diagnostics["coordinator"]["last_update_success"] is True


async def test_renaming_in_ciconia_renames_the_device(hass, aioclient_mock, account_entry):
    mock_car(aioclient_mock)
    await _setup(hass, account_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", json=device_list((CAR, "Mum's Car", "ready")))
    aioclient_mock.get(f"{BASE}/api/v1/devices/{CAR}", json=device_payload(CAR, "Mum's Car"))
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    [device] = dr.async_entries_for_config_entry(registry, account_entry.entry_id)
    assert device.name == "Mum's Car"
    # Entity ids stay put, so automations keep working.
    assert hass.states.get("device_tracker.dad_s_car") is not None
