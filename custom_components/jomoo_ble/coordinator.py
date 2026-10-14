"""Periodic read-only queries and non-optimistic control read-back."""

from __future__ import annotations

from datetime import timedelta
import logging

from bleak.exc import BleakError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bluetooth import make_session
from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_NAME_PREFIX,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .lib.client import SessionError, Snapshot
from .lib.protocol import Action, ProtocolError

_LOGGER = logging.getLogger(__name__)
ERRORS = (BleakError, OSError, TimeoutError, SessionError, ProtocolError)


class JomooCoordinator(DataUpdateCoordinator[Snapshot]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.session = make_session(hass, entry.data["address"], entry.data[CONF_NAME_PREFIX])
        self.controls_enabled = entry.options.get(
            CONF_ENABLE_CONTROLS, entry.data.get(CONF_ENABLE_CONTROLS, False)
        )
        interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> Snapshot:
        try:
            return await self.session.poll()
        except ERRORS as err:
            # Transport exceptions can include private proxy/MAC details.
            raise UpdateFailed(
                "Bluetooth status query failed; check proxy and single connection"
            ) from err

    async def async_command(self, action: Action) -> None:
        if not self.controls_enabled:
            raise HomeAssistantError(
                "Enable controls in integration options after read-only acceptance"
            )
        try:
            observed = await self.session.command(action)
        except ERRORS as err:
            self.async_set_update_error(
                UpdateFailed("Control was not confirmed; no automatic retry")
            )
            raise HomeAssistantError(
                "Control failed or unconfirmed; inspect the device before retrying"
            ) from err
        self.async_set_updated_data(observed)

    async def async_close(self) -> None:
        await self.async_shutdown()
        await self.session.close()
