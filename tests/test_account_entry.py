"""Account-wide entries: every tracker on the account, kept in sync."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ciconia.const import DOMAIN

from .conftest import device_list, device_payload

BASE = "http://example.local"


def mock_account(aioclient_mock, devices, positions):
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/api/v1/devices", json=device_list(*devices))
    for device_id, response in positions.items():
        if isinstance(response, int):
            aioclient_mock.get(
                f"{BASE}/api/v1/devices/{device_id}", status=response, json={"error": "x"}
            )
        else:
            aioclient_mock.get(f"{BASE}/api/v1/devices/{device_id}", json=response)


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _tracker_ids(hass, entry):
    registry = dr.async_get(hass)
    return {
        identifier
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        for _, identifier in device.identifiers
    }


async def test_tracks_every_ready_device(hass, aioclient_mock, account_entry):
    mock_account(
        aioclient_mock,
        [
            ("dv_car", "Car", "ready"),
            ("dv_van", "Van", "ready"),
            ("dv_new", "Trailer", "provisioning"),
        ],
        {
            "dv_car": device_payload("dv_car", "Car"),
            "dv_van": device_payload("dv_van", "Van", latitude=50.0),
        },
    )

    await _setup(hass, account_entry)

    assert account_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("device_tracker.car").attributes["latitude"] == 52.2296756
    assert hass.states.get("device_tracker.van").attributes["latitude"] == 50.0
    assert hass.states.get("device_tracker.trailer") is None
    assert _tracker_ids(hass, account_entry) == {"dv_car", "dv_van"}


async def test_excluded_devices_are_skipped(hass, aioclient_mock):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{BASE}::ac_123",
        data={"base_url": BASE, "api_token": "tok", "account_id": "ac_123"},
        options={"excluded_devices": ["dv_van"]},
    )
    mock_account(
        aioclient_mock,
        [("dv_car", "Car", "ready"), ("dv_van", "Van", "ready")],
        {"dv_car": device_payload("dv_car", "Car")},
    )

    await _setup(hass, entry)

    assert hass.states.get("device_tracker.car") is not None
    assert hass.states.get("device_tracker.van") is None
    assert not any(call[1].path.endswith("dv_van") for call in aioclient_mock.mock_calls)


async def test_new_devices_appear_and_removed_ones_go(hass, aioclient_mock, account_entry):
    mock_account(
        aioclient_mock, [("dv_car", "Car", "ready")], {"dv_car": device_payload("dv_car", "Car")}
    )
    coordinator = await _setup(hass, account_entry)
    assert hass.states.get("device_tracker.van") is None

    # The van gets activated.
    mock_account(
        aioclient_mock,
        [("dv_car", "Car", "ready"), ("dv_van", "Van", "ready")],
        {"dv_car": device_payload("dv_car", "Car"), "dv_van": device_payload("dv_van", "Van")},
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("device_tracker.van") is not None
    assert _tracker_ids(hass, account_entry) == {"dv_car", "dv_van"}

    # The car is removed from the account.
    mock_account(
        aioclient_mock, [("dv_van", "Van", "ready")], {"dv_van": device_payload("dv_van", "Van")}
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _tracker_ids(hass, account_entry) == {"dv_van"}
    assert hass.states.get("device_tracker.car") is None


async def test_one_failing_device_does_not_take_down_the_rest(hass, aioclient_mock, account_entry):
    mock_account(
        aioclient_mock,
        [("dv_car", "Car", "ready"), ("dv_van", "Van", "ready")],
        {"dv_car": device_payload("dv_car", "Car"), "dv_van": 502},
    )

    await _setup(hass, account_entry)

    assert hass.states.get("device_tracker.car").state != STATE_UNAVAILABLE
    assert hass.states.get("device_tracker.van").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.van_altitude").state == STATE_UNAVAILABLE


async def test_all_devices_failing_retries_setup(hass, aioclient_mock, account_entry):
    mock_account(aioclient_mock, [("dv_car", "Car", "ready")], {"dv_car": 502})

    account_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(account_entry.entry_id)
    assert account_entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_token_starts_reauth(hass, aioclient_mock, account_entry):
    aioclient_mock.get(f"{BASE}/api/v1/devices", status=401, json={"error": "unauthorized"})

    account_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_device_removed_between_list_and_fetch_is_not_an_auth_error(
    hass, aioclient_mock, account_entry
):
    mock_account(
        aioclient_mock,
        [("dv_car", "Car", "ready"), ("dv_gone", "Gone", "ready")],
        {"dv_car": device_payload("dv_car", "Car"), "dv_gone": 401},
    )

    await _setup(hass, account_entry)

    assert account_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("device_tracker.car") is not None


async def test_options_flow_picks_devices(hass, aioclient_mock, account_entry):
    mock_account(
        aioclient_mock,
        [("dv_car", "Car", "ready"), ("dv_van", "Van", "ready")],
        {"dv_car": device_payload("dv_car", "Car"), "dv_van": device_payload("dv_van", "Van")},
    )
    await _setup(hass, account_entry)

    result = await hass.config_entries.options.async_init(account_entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"devices": ["dv_car"], "scan_interval": 60},
    )
    await hass.async_block_till_done()

    assert account_entry.options == {
        "excluded_devices": ["dv_van"],
        "scan_interval": 60,
    }
    # The update listener reloads the entry, dropping the van.
    assert _tracker_ids(hass, account_entry) == {"dv_car"}
