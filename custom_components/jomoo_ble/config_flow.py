"""Manual MAC setup, read-only validation, and explicit control opt-in."""

from __future__ import annotations

import re
from typing import Any

from bleak.exc import BleakError
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .bluetooth import make_session
from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_NAME_PREFIX,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PREFIX,
    DOMAIN,
)
from .lib.client import SessionError
from .lib.protocol import ProtocolError

MAC = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")


class JomooConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            prefix = user_input[CONF_NAME_PREFIX]
            # Validate source text before normalization; no repair of malformed IDs.
            if not MAC.fullmatch(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif not prefix:
                errors[CONF_NAME_PREFIX] = "invalid_prefix"
            else:
                address = address.upper()
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                session = make_session(self.hass, address, prefix)
                try:
                    await session.poll()
                except (BleakError, OSError, TimeoutError, SessionError, ProtocolError):
                    errors["base"] = "cannot_connect"
                finally:
                    try:
                        await session.close()
                    except (BleakError, OSError, TimeoutError, SessionError):
                        errors["base"] = "cannot_connect"
                if not errors:
                    return self.async_create_entry(
                        title="JOMOO ZS800J",
                        data={
                            CONF_ADDRESS: address,
                            CONF_NAME_PREFIX: prefix,
                            CONF_ENABLE_CONTROLS: False,
                        },
                    )
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Required(CONF_NAME_PREFIX, default=DEFAULT_PREFIX): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return JomooOptionsFlow()


class JomooOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_CONTROLS,
                        default=self.config_entry.options.get(CONF_ENABLE_CONTROLS, False),
                    ): bool,
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                }
            ),
        )
