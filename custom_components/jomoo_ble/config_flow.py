"""Bluetooth discovery or manual MAC setup, one read-only check, explicit opt-ins."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from bleak.exc import BleakError
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .bluetooth import make_session, supported_name
from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_ENABLE_EXPERIMENTAL,
    CONF_NAME_PREFIX,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PREFIX,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    MODEL,
)
from .lib.client import SessionError
from .lib.protocol import ProtocolError

MAC = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
ERRORS = (BleakError, OSError, TimeoutError, SessionError, ProtocolError)


class JomooConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: str | None = None

    async def _validate(self, address: str, prefix: str) -> str | None:
        session = make_session(self.hass, address, prefix)
        error = None
        try:
            await session.poll()
        except ERRORS:
            error = "cannot_connect"
        try:
            await session.close()
        except ERRORS:
            error = "cannot_connect"
        return error

    def _create(self, address: str, prefix: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=f"JOMOO {MODEL}",
            data={CONF_ADDRESS: address, CONF_NAME_PREFIX: prefix},
            options={
                CONF_ENABLE_CONTROLS: False,
                CONF_ENABLE_EXPERIMENTAL: False,
                CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
            },
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        if not supported_name(discovery_info.name, DEFAULT_PREFIX):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()
        self._discovered = discovery_info.address.upper()
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._validate(self._discovered, DEFAULT_PREFIX)
            if error is None:
                return self._create(self._discovered, DEFAULT_PREFIX)
            errors["base"] = error
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            errors=errors,
            description_placeholders={"name": self.context["title_placeholders"]["name"]},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip()
            prefix = user_input[CONF_NAME_PREFIX]
            if not MAC.fullmatch(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif not prefix:
                errors[CONF_NAME_PREFIX] = "invalid_prefix"
            else:
                address = address.upper()
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                error = await self._validate(address, prefix)
                if error is None:
                    return self._create(address, prefix)
                errors["base"] = error
        suggested = next(
            (
                info.address
                for info in async_discovered_service_info(self.hass, connectable=True)
                if supported_name(info.name, DEFAULT_PREFIX)
                and info.address.upper() not in self._async_current_ids()
            ),
            "",
        )
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS, default=suggested): str,
                    vol.Required(CONF_NAME_PREFIX, default=DEFAULT_PREFIX): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return JomooOptionsFlow()


def _valid_interval(value: Any) -> int:
    value = int(value)
    if value != 0 and not MIN_POLL_INTERVAL <= value <= MAX_POLL_INTERVAL:
        raise vol.Invalid("poll_interval")
    return value


class JomooOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input[CONF_POLL_INTERVAL] = _valid_interval(user_input[CONF_POLL_INTERVAL])
            except (vol.Invalid, ValueError):
                errors[CONF_POLL_INTERVAL] = "invalid_interval"
            else:
                return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_CONTROLS, default=options.get(CONF_ENABLE_CONTROLS, False)
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_EXPERIMENTAL,
                        default=options.get(CONF_ENABLE_EXPERIMENTAL, False),
                    ): bool,
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                    ): vol.Coerce(int),
                }
            ),
        )
