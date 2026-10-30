"""Config flow for Ciconia.

Setup is "link with a code" (like signing a TV in to an account): the flow
asks Ciconia for a short code, shows it with a link, and waits while
the user approves it on the Ciconia website. Approval hands back the
account's api_token, so nobody copies ids or tokens around. One config
entry then covers the whole account: every device is tracked except the
ones the user unticks, and devices added later show up on their own.
Reauth (the token was regenerated) is another link code for the same
account; reconfigure changes the server address and links again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

try:
    import probatio as vol
except ImportError:  # Home Assistant before 2026.10 uses voluptuous
    import voluptuous as vol  # type: ignore[no-redef]

from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CiconiaApiClient,
    CiconiaApiError,
    CiconiaAuthError,
    CiconiaLinkError,
    CiconiaUpstreamError,
    DeviceSummary,
    LinkRequest,
    LinkResult,
    async_create_link_request,
    async_poll_link_request,
)
from .const import (
    CONF_ACCOUNT_EMAIL,
    CONF_ACCOUNT_ID,
    CONF_BASE_URL,
    CONF_EXCLUDED_DEVICES,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CONF_DEVICES = "devices"
SECTION_ADVANCED = "advanced"


def _server_schema(default: str) -> vol.Schema:
    """The server address, folded away: nearly everyone uses the hosted one."""
    return vol.Schema(
        {
            vol.Required(SECTION_ADVANCED): section(
                vol.Schema({vol.Required(CONF_BASE_URL, default=default): str}),
                {"collapsed": True},
            )
        }
    )


def _base_url_from(user_input: dict[str, Any], default: str) -> str | None:
    """The submitted server address, normalised; None if it isn't a URL."""
    url = str(user_input.get(SECTION_ADVANCED, {}).get(CONF_BASE_URL) or default).strip()
    if not url.startswith(("https://", "http://")):
        return None
    return url.rstrip("/")


async def _async_list_devices(
    hass: HomeAssistant, base_url: str, api_token: str
) -> list[DeviceSummary]:
    client = CiconiaApiClient(async_get_clientsession(hass), base_url, api_token)
    return await client.async_list_devices()


def _device_choices(devices: list[DeviceSummary]) -> dict[str, str]:
    return {
        d.device_id: d.name if d.ready else f"{d.name} (activating, added once it's active)"
        for d in devices
    }


class CiconiaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ciconia."""

    VERSION = 1

    def __init__(self) -> None:
        """Start on the hosted server with nothing linked yet."""
        self._base_url = DEFAULT_BASE_URL
        self._link_request: LinkRequest | None = None
        self._link_task: asyncio.Task[LinkResult] | None = None
        self._link_error: str | None = None
        self._link_result: LinkResult | None = None
        self._devices: list[DeviceSummary] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm, then get a link code (server address folded under Advanced)."""
        return await self._async_server_step("user", user_input, DEFAULT_BASE_URL)

    async def _async_server_step(
        self, step_id: str, user_input: dict[str, Any] | None, default: str
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = _base_url_from(user_input, default)
            if base_url is None:
                errors["base"] = "invalid_url"
            else:
                self._base_url = base_url
                if (error := await self._async_request_code()) is None:
                    return await self.async_step_link()
                errors["base"] = error
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _server_schema(default),
                {SECTION_ADVANCED: {CONF_BASE_URL: self._base_url if user_input else default}},
            ),
            errors=errors,
        )

    async def _async_request_code(self) -> str | None:
        """Ask the server for a link code; an error key if it can't be reached."""
        try:
            self._link_request = await async_create_link_request(
                async_get_clientsession(self.hass),
                self._base_url,
                f"Home Assistant ({self.hass.config.location_name})",
            )
        except CiconiaUpstreamError:
            _LOGGER.debug("Could not get a link code from %s", self._base_url, exc_info=True)
            return "cannot_connect"
        self._link_task = None
        return None

    # ---------------------------------------------------------------- linking

    async def async_step_link(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the code and wait (in the background) for the user to approve it."""
        if self._link_request is None and (error := await self._async_request_code()):
            return self.async_abort(reason=error)
        assert self._link_request is not None

        if self._link_task is None:
            self._link_task = self.hass.async_create_task(self._async_wait_for_approval())

        if not self._link_task.done():
            return self.async_show_progress(
                step_id="link",
                progress_action="wait_for_approval",
                description_placeholders={
                    "code": self._link_request.user_code,
                    "url": self._link_request.verification_url_complete,
                    "minutes": str(max(1, self._link_request.expires_in // 60)),
                },
                progress_task=self._link_task,
            )

        try:
            self._link_result = self._link_task.result()
        except CiconiaLinkError as err:
            self._link_error = "link_denied" if err.reason == "denied" else "link_expired"
            return self.async_show_progress_done(next_step_id="link_failed")
        return self.async_show_progress_done(next_step_id="linked")

    async def _async_wait_for_approval(self) -> LinkResult:
        assert self._link_request is not None
        request = self._link_request
        session = async_get_clientsession(self.hass)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + request.expires_in
        # Always wait and poll at least once, so the task never finishes
        # before the progress step has been shown.
        while True:
            await asyncio.sleep(request.interval)
            try:
                result = await async_poll_link_request(session, self._base_url, request.device_code)
            except CiconiaUpstreamError:
                _LOGGER.debug("Link poll failed, retrying", exc_info=True)
                result = None
            if result is not None:
                return result
            if loop.time() >= deadline:
                raise CiconiaLinkError("expired")

    async def async_step_link_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Explain what went wrong; submitting starts over with a new code."""
        if user_input is not None:
            self._link_request = None
            self._link_task = None
            self._link_error = None
            return await self.async_step_link()
        return self.async_show_form(
            step_id="link_failed", errors={"base": self._link_error or "unknown"}
        )

    async def async_step_linked(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Approved: create the entry, or update the one being reauthed/moved."""
        assert self._link_result is not None
        result = self._link_result
        if self.source == config_entries.SOURCE_REAUTH:
            return await self._async_finish_reauth(result)
        if self.source == config_entries.SOURCE_RECONFIGURE:
            return await self._async_finish_reconfigure(result)

        await self.async_set_unique_id(f"{self._base_url}::{result.account_id}")
        # Linking an account that's already set up just refreshes its token.
        self._abort_if_unique_id_configured(updates={CONF_API_TOKEN: result.api_token})

        try:
            devices = await _async_list_devices(self.hass, self._base_url, result.api_token)
        except CiconiaApiError:
            return self.async_abort(reason="cannot_connect")
        self._devices = devices
        if not self._devices:
            return self._async_create_account_entry(excluded=[])
        return await self.async_step_devices()

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Untick trackers that shouldn't be in Home Assistant."""
        choices = _device_choices(self._devices)
        if user_input is not None:
            selected = set(user_input[CONF_DEVICES])
            return self._async_create_account_entry(
                excluded=[device_id for device_id in choices if device_id not in selected]
            )
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {vol.Optional(CONF_DEVICES, default=list(choices)): cv.multi_select(choices)}
            ),
        )

    @callback
    def _async_create_account_entry(self, excluded: list[str]) -> config_entries.ConfigFlowResult:
        assert self._link_result is not None
        result = self._link_result
        return self.async_create_entry(
            title=result.account_email or "Ciconia",
            data={
                CONF_BASE_URL: self._base_url,
                CONF_API_TOKEN: result.api_token,
                CONF_ACCOUNT_ID: result.account_id,
                CONF_ACCOUNT_EMAIL: result.account_email,
            },
            options={CONF_EXCLUDED_DEVICES: excluded},
        )

    # ----------------------------------------------------------------- reauth

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """The token stopped working (regenerated or connection removed)."""
        self._base_url = entry_data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Explain why, then link again with a new code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if (error := await self._async_request_code()) is None:
                return await self.async_step_link()
            errors["base"] = error
        return self.async_show_form(step_id="reauth_confirm", errors=errors)

    async def _async_finish_reauth(self, result: LinkResult) -> config_entries.ConfigFlowResult:
        entry = self._get_reauth_entry()
        if entry.data.get(CONF_ACCOUNT_ID) != result.account_id:
            return self.async_abort(reason="wrong_account")

        return self.async_update_reload_and_abort(
            entry, data_updates={CONF_API_TOKEN: result.api_token}
        )

    # ------------------------------------------------------------ reconfigure

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Move the entry to another server address (same account), linking again."""
        current = self._get_reconfigure_entry().data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        return await self._async_server_step("reconfigure", user_input, current)

    async def _async_finish_reconfigure(
        self, result: LinkResult
    ) -> config_entries.ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_ACCOUNT_ID) != result.account_id:
            return self.async_abort(reason="wrong_account")
        unique_id = f"{self._base_url}::{result.account_id}"
        if any(
            other.unique_id == unique_id and other.entry_id != entry.entry_id
            for other in self._async_current_entries(include_ignore=False)
        ):
            return self.async_abort(reason="already_configured")
        return self.async_update_reload_and_abort(
            entry,
            unique_id=unique_id,
            data_updates={
                CONF_BASE_URL: self._base_url,
                CONF_API_TOKEN: result.api_token,
                CONF_ACCOUNT_EMAIL: result.account_email,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CiconiaOptionsFlow:
        """Options: trackers and polling interval."""
        return CiconiaOptionsFlow()


class CiconiaOptionsFlow(config_entries.OptionsFlow):
    """Which trackers to include and the polling interval.

    The server address isn't here: the token belongs to that server, so
    changing it means linking again - that's the reconfigure flow.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """One form: trackers and polling interval."""
        entry = self.config_entry
        try:
            devices = await _async_list_devices(
                self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_TOKEN]
            )
        except CiconiaAuthError:
            return self.async_abort(reason="invalid_auth")
        except CiconiaUpstreamError:
            return self.async_abort(reason="cannot_connect")
        choices = _device_choices(devices)

        if user_input is not None:
            selected = set(user_input.get(CONF_DEVICES, []))
            return self.async_create_entry(
                title="",
                data={
                    CONF_EXCLUDED_DEVICES: [d for d in choices if d not in selected],
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                },
            )

        excluded = set(entry.options.get(CONF_EXCLUDED_DEVICES, []))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DEVICES, default=[d for d in choices if d not in excluded]
                    ): cv.multi_select(choices),
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
                }
            ),
        )
