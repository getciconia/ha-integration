"""Tests for the Ciconia API client."""

from __future__ import annotations

from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.ciconia.api import (
    CiconiaApiClient,
    CiconiaAuthError,
    CiconiaUpstreamError,
)

from .conftest import SAMPLE_DEVICE_PAYLOAD


async def test_async_get_device_success(aioclient_mock, hass):
    aioclient_mock.get(
        "http://example.local/api/v1/devices/dv_8f2a1c4b9e6d",
        json=SAMPLE_DEVICE_PAYLOAD,
    )
    session = async_get_clientsession(hass)
    client = CiconiaApiClient(session, "http://example.local", "tok")
    device = await client.async_get_device("dv_8f2a1c4b9e6d")

    assert device.device_id == "dv_8f2a1c4b9e6d"
    assert device.name == "Dad's Car"
    assert device.latitude == 52.2296756
    assert device.battery_level == 87
    assert device.attributes == {"odometer": 126092}


async def test_async_get_device_401_raises_auth_error(aioclient_mock, hass):
    aioclient_mock.get(
        "http://example.local/api/v1/devices/bad_id",
        status=401,
        json={"error": "unauthorized"},
    )
    session = async_get_clientsession(hass)
    client = CiconiaApiClient(session, "http://example.local", "tok")
    with pytest.raises(CiconiaAuthError):
        await client.async_get_device("bad_id")


async def test_async_get_device_502_raises_upstream_error(aioclient_mock, hass):
    aioclient_mock.get(
        "http://example.local/api/v1/devices/dv_8f2a1c4b9e6d",
        status=502,
        json={"error": "upstream_unavailable"},
    )
    session = async_get_clientsession(hass)
    client = CiconiaApiClient(session, "http://example.local", "tok")
    with pytest.raises(CiconiaUpstreamError):
        await client.async_get_device("dv_8f2a1c4b9e6d")


async def test_async_get_device_null_fields(aioclient_mock, hass):
    """No fix yet - every field except device_id/name is null."""
    aioclient_mock.get(
        "http://example.local/api/v1/devices/dv_new",
        json={
            "device": {
                "device_id": "dv_new",
                "name": "Brand New",
                "model": None,
                "latitude": None,
                "longitude": None,
                "altitude": None,
                "speed": None,
                "battery_level": None,
                "gsm_signal": None,
                "gsm_operator_code": None,
                "chip_temperature": None,
                "satellites": None,
                "fixed_time": None,
                "fix_age_seconds": None,
                "attributes": {},
            }
        },
    )
    session = async_get_clientsession(hass)
    client = CiconiaApiClient(session, "http://example.local", "tok")
    device = await client.async_get_device("dv_new")

    assert device.latitude is None
    assert device.attributes == {}
