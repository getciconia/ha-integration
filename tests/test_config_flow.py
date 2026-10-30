"""Tests for the Ciconia config flow (link with a code), reauth and reconfigure."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ciconia.api import CiconiaUpstreamError, LinkResult
from custom_components.ciconia.const import DEFAULT_BASE_URL, DOMAIN

from .conftest import device_list

BASE = DEFAULT_BASE_URL
OTHER = "http://dev.local:3000"
LINK_RESPONSE = {
    "user_code": "K7QX-49MP",
    "device_code": "secret",
    "verification_url": f"{BASE}/link",
    "verification_url_complete": f"{BASE}/link?code=K7QX-49MP",
    "expires_in": 600,
    "interval": 0,
}
APPROVED = {
    "status": "approved",
    "api_token": "tok",
    "account_id": "ac_123",
    "account_email": "adam@example.com",
}


@pytest.fixture(autouse=True)
def no_setup():
    """The flow is under test, not entry setup."""
    with patch("custom_components.ciconia.async_setup_entry", return_value=True):
        yield


def mock_link(aioclient_mock, poll_response, base=BASE, devices=None, link=LINK_RESPONSE):
    aioclient_mock.post(f"{base}/api/v1/link_requests", json=link, status=201)
    aioclient_mock.post(f"{base}/api/v1/link_requests/poll", json=poll_response)
    aioclient_mock.get(
        f"{base}/api/v1/devices",
        json=devices
        or device_list(
            ("dv_car", "Car", "ready"),
            ("dv_bike", "Bike", "ready"),
            ("dv_new", "Trailer", "provisioning"),
        ),
    )


def server(url: str) -> dict:
    """User input of the server form (the address sits in a folded section)."""
    return {"advanced": {"base_url": url}}


async def _wait(hass, result):
    """Let the background approval finish and move on."""
    assert result["type"] == FlowResultType.SHOW_PROGRESS, result
    assert result["step_id"] == "link"
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def _start_and_wait(hass, base=BASE):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server(base))
    assert result["description_placeholders"]["code"] == "K7QX-49MP"
    assert result["description_placeholders"]["url"] == f"{BASE}/link?code=K7QX-49MP"
    assert result["description_placeholders"]["minutes"] in ("1", "10")
    return await _wait(hass, result)


async def test_link_creates_account_entry(hass, aioclient_mock):
    mock_link(aioclient_mock, APPROVED)

    result = await _start_and_wait(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "devices"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"devices": ["dv_car", "dv_new"]}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "adam@example.com"
    assert result["data"] == {
        "base_url": BASE,
        "api_token": "tok",
        "account_id": "ac_123",
        "account_email": "adam@example.com",
    }
    assert result["options"] == {"excluded_devices": ["dv_bike"]}
    assert result["result"].unique_id == f"{BASE}::ac_123"


async def test_link_without_devices_skips_the_picker(hass, aioclient_mock):
    mock_link(aioclient_mock, APPROVED, devices={"devices": []})

    result = await _start_and_wait(hass)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"] == {"excluded_devices": []}


async def test_link_sends_the_instance_name(hass, aioclient_mock):
    hass.config.location_name = "Cottage"
    mock_link(aioclient_mock, APPROVED)

    await _start_and_wait(hass)

    assert aioclient_mock.mock_calls[0][2] == {"client_name": "Home Assistant (Cottage)"}


async def test_link_denied_offers_a_retry(hass, aioclient_mock):
    mock_link(aioclient_mock, {"status": "denied"})

    result = await _start_and_wait(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "link_failed"
    assert result["errors"] == {"base": "link_denied"}

    aioclient_mock.clear_requests()
    mock_link(aioclient_mock, APPROVED)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _wait(hass, result)
    assert result["step_id"] == "devices"


async def test_retry_when_the_server_went_away(hass, aioclient_mock):
    mock_link(aioclient_mock, {"status": "denied"})
    result = await _start_and_wait(hass)

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/api/v1/link_requests", status=500)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_link_expired(hass, aioclient_mock):
    mock_link(aioclient_mock, {"status": "expired"})

    result = await _start_and_wait(hass)

    assert result["step_id"] == "link_failed"
    assert result["errors"] == {"base": "link_expired"}


async def test_unknown_link_request_counts_as_expired(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/api/v1/link_requests", json=LINK_RESPONSE, status=201)
    aioclient_mock.post(f"{BASE}/api/v1/link_requests/poll", status=404)

    result = await _start_and_wait(hass)

    assert result["errors"] == {"base": "link_expired"}


async def test_code_runs_out_while_waiting(hass, aioclient_mock):
    mock_link(aioclient_mock, {"status": "pending"}, link={**LINK_RESPONSE, "expires_in": 0})

    result = await _start_and_wait(hass)

    assert result["errors"] == {"base": "link_expired"}


async def test_poll_errors_are_retried(hass, aioclient_mock):
    mock_link(aioclient_mock, APPROVED)
    approved = LinkResult(api_token="tok", account_id="ac_123", account_email=None)
    with patch(
        "custom_components.ciconia.config_flow.async_poll_link_request",
        side_effect=[CiconiaUpstreamError("blip"), None, approved],
    ) as poll:
        result = await _start_and_wait(hass)

    assert poll.call_count == 3
    assert result["step_id"] == "devices"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"devices": []})
    assert result["title"] == "Ciconia"  # no email handed over


async def test_cannot_reach_server_shows_an_error(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/api/v1/link_requests", status=500)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server(BASE))

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    mock_link(aioclient_mock, APPROVED)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server(BASE))
    result = await _wait(hass, result)
    assert result["step_id"] == "devices"


async def test_server_without_linking_support(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/api/v1/link_requests", status=404)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server(BASE))

    assert result["errors"] == {"base": "cannot_connect"}


async def test_rejects_an_address_that_is_not_a_url(hass, aioclient_mock):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server("dev.local"))

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}
    assert aioclient_mock.call_count == 0


async def test_can_pick_another_server(hass, aioclient_mock):
    mock_link(aioclient_mock, APPROVED, base=OTHER)

    result = await _start_and_wait(hass, base=OTHER + "/")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"devices": []})

    assert result["data"]["base_url"] == OTHER
    assert result["result"].unique_id == f"{OTHER}::ac_123"


async def test_device_list_failing_after_approval(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/api/v1/link_requests", json=LINK_RESPONSE, status=201)
    aioclient_mock.post(f"{BASE}/api/v1/link_requests/poll", json=APPROVED)
    aioclient_mock.get(f"{BASE}/api/v1/devices", status=502, json={"error": "x"})

    result = await _start_and_wait(hass)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_linking_same_account_again_refreshes_the_token(hass, aioclient_mock):
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{BASE}::ac_123",
        data={"base_url": BASE, "api_token": "old", "account_id": "ac_123"},
    )
    existing.add_to_hass(hass)
    mock_link(aioclient_mock, APPROVED)

    result = await _start_and_wait(hass)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert existing.data["api_token"] == "tok"


# --------------------------------------------------------------------- reauth


async def test_reauth_account_entry(hass, aioclient_mock, account_entry):
    account_entry.add_to_hass(hass)
    mock_link(aioclient_mock, {**APPROVED, "api_token": "new"}, base="http://example.local")

    result = await account_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _wait(hass, result)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert account_entry.data["api_token"] == "new"


async def test_reauth_with_another_account_is_refused(hass, aioclient_mock, account_entry):
    account_entry.add_to_hass(hass)
    mock_link(aioclient_mock, {**APPROVED, "account_id": "ac_other"}, base="http://example.local")

    result = await account_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _wait(hass, result)

    assert result["reason"] == "wrong_account"
    assert account_entry.data["api_token"] == "tok"


async def test_reauth_when_the_server_is_down(hass, aioclient_mock, account_entry):
    account_entry.add_to_hass(hass)
    aioclient_mock.post("http://example.local/api/v1/link_requests", exc=TimeoutError)

    result = await account_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------- reconfigure


async def test_reconfigure_moves_to_another_server(hass, aioclient_mock, account_entry):
    account_entry.add_to_hass(hass)
    mock_link(aioclient_mock, {**APPROVED, "api_token": "new"}, base=OTHER)

    result = await account_entry.start_reconfigure_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server(OTHER))
    result = await _wait(hass, result)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert account_entry.data["base_url"] == OTHER
    assert account_entry.data["api_token"] == "new"
    assert account_entry.unique_id == f"{OTHER}::ac_123"


async def test_reconfigure_with_another_account_is_refused(hass, aioclient_mock, account_entry):
    account_entry.add_to_hass(hass)
    mock_link(aioclient_mock, {**APPROVED, "account_id": "ac_other"}, base=OTHER)

    result = await account_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server(OTHER))
    result = await _wait(hass, result)

    assert result["reason"] == "wrong_account"
    assert account_entry.data["base_url"] == "http://example.local"


async def test_reconfigure_onto_an_entry_that_exists(hass, aioclient_mock, account_entry):
    account_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{OTHER}::ac_123",
        data={"base_url": OTHER, "api_token": "x", "account_id": "ac_123"},
    ).add_to_hass(hass)
    mock_link(aioclient_mock, APPROVED, base=OTHER)

    result = await account_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server(OTHER))
    result = await _wait(hass, result)

    assert result["reason"] == "already_configured"
    assert account_entry.data["base_url"] == "http://example.local"


async def test_reconfigure_bad_address(hass, aioclient_mock, account_entry):
    account_entry.add_to_hass(hass)

    result = await account_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], server("ftp://x"))

    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "invalid_url"}
