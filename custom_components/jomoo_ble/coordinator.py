"""On-demand refreshes, optional slow polling, non-optimistic commands."""

from __future__ import annotations

from datetime import timedelta
import logging

from bleak.exc import BleakError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .bluetooth import make_session
from .const import (
    CONF_ENABLE_STATUS_STREAM,
    CONF_ENABLE_CONTROLS,
    CONF_ENABLE_EXPERIMENTAL,
    CONF_NAME_PREFIX,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .lib.client import (
    FLUSH_UNCONFIRMED,
    Command,
    CommandRefused,
    SessionError,
    Snapshot,
    VerificationError,
)
from .lib.protocol import ProtocolError

_LOGGER = logging.getLogger(__name__)
ERRORS = (BleakError, OSError, TimeoutError, SessionError, ProtocolError)


def _option(entry: ConfigEntry, key: str, default):
    return entry.options.get(key, entry.data.get(key, default))


class JomooCoordinator(DataUpdateCoordinator[Snapshot | None]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.address: str = entry.data["address"]
        self.session = make_session(hass, self.address, entry.data[CONF_NAME_PREFIX])
        self.controls_enabled: bool = _option(entry, CONF_ENABLE_CONTROLS, False)
        self.experimental_enabled: bool = _option(entry, CONF_ENABLE_EXPERIMENTAL, False)
        self.last_refresh = None
        self.last_received = None
        self.stream_enabled = bool(_option(entry, CONF_ENABLE_STATUS_STREAM, False))
        self.stream_error = "not_connected" if self.stream_enabled else None
        if self.stream_enabled:
            self.session.enable_stream(self._stream_changed)
        self.last_warning: str | None = None
        interval = int(_option(entry, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval)
            if interval > 0 and not self.stream_enabled
            else None,
            always_update=True,
        )
        self.data = None

    @callback
    def _stream_changed(self) -> None:
        snapshot = self.session.stream_snapshot
        self.last_received = self.session.last_received
        if self.session.stream_connected and snapshot is not None:
            self.stream_error = None
            self.async_set_updated_data(snapshot)
        else:
            self.stream_error = "disconnect_uncertain" if self.session.blocked else "disconnected"
            self.data = None
            self.async_update_listeners()

    def _publish(self, snapshot: Snapshot) -> None:
        if self.stream_enabled and not self.session.stream_connected:
            self._stream_changed()
            return
        self.last_refresh = dt_util.utcnow()
        self.last_warning = snapshot.warning
        if self.stream_enabled:
            live = self.session.stream_snapshot
            if live is not None:
                snapshot = Snapshot(
                    live.frames, warning=snapshot.warning, received_at=live.received_at
                )
        self.async_set_updated_data(snapshot)

    async def _async_update_data(self) -> Snapshot | None:
        try:
            snapshot = await self.session.poll()
        except ERRORS as err:
            if self.stream_enabled:
                self._stream_changed()
            # Transport errors may include proxy or address details; keep the message generic.
            raise UpdateFailed(
                "Bluetooth status query failed; check the proxy and that no other app is connected"
            ) from err
        self.last_refresh = dt_util.utcnow()
        self.last_warning = None
        return self.session.stream_snapshot if self.stream_enabled else snapshot

    async def async_refresh_now(self) -> None:
        try:
            snapshot = await self.session.poll()
        except ERRORS as err:
            if self.stream_enabled:
                self._stream_changed()
            raise HomeAssistantError(
                "Status refresh failed; check the proxy and that no other app is connected"
            ) from err
        self._publish(snapshot)

    def _require_controls(self, experimental: bool = False) -> None:
        if not self.controls_enabled:
            raise HomeAssistantError("Enable controls in the integration options first")
        if experimental and not self.experimental_enabled:
            raise HomeAssistantError(
                "Enable experimental controls in the integration options first"
            )

    async def async_command(self, command: Command, experimental: bool = False) -> None:
        self._require_controls(experimental)
        try:
            snapshot = await self.session.command(command)
        except CommandRefused as err:
            raise HomeAssistantError(str(err)) from err
        except VerificationError as err:
            detail = f": {sorted(err.diff)}" if err.diff else ""
            raise HomeAssistantError(
                f"Command sent but not confirmed{detail}; inspect the toilet before retrying"
            ) from err
        except ERRORS as err:
            if self.stream_enabled and not self.session.stream_connected:
                raise HomeAssistantError(
                    "Live connection unavailable or release uncertain; control blocked. "
                    "Check connection diagnostics; use Refresh status for recovery, "
                    "or restart HA after checking an uncertain release"
                ) from err
            raise HomeAssistantError(
                "Command failed or unconfirmed; inspect the toilet before retrying"
            ) from err
        self._publish(snapshot)
        if snapshot.warning == FLUSH_UNCONFIRMED:
            _LOGGER.warning("Flush command sent but the flush flag was not observed")

    async def async_stop(self, _event) -> None:
        await self.async_close()

    async def async_close(self) -> None:
        await self.async_shutdown()
        await self.session.close()
