"""On-demand refreshes, optional slow polling, non-optimistic commands, shower guard."""

from __future__ import annotations

from datetime import timedelta
import logging

from bleak.exc import BleakError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .bluetooth import make_session
from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_ENABLE_EXPERIMENTAL,
    CONF_NAME_PREFIX,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    STORAGE_VERSION,
)
from .lib.client import (
    FLUSH_UNCONFIRMED,
    Command,
    CommandRefused,
    SessionError,
    SetSettings,
    Snapshot,
    VerificationError,
)
from .lib.guard import GuardState, ShowerGuard
from .lib.protocol import ProtocolError

_LOGGER = logging.getLogger(__name__)
ERRORS = (BleakError, OSError, TimeoutError, SessionError, ProtocolError)


class _HassStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.guard")

    async def load(self):
        return await self._store.async_load()

    async def save(self, data: dict) -> None:
        await self._store.async_save(data)


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
        self.last_warning: str | None = None
        self.guard = ShowerGuard(
            self.session, _HassStore(hass, entry.entry_id), self._guard_changed
        )
        interval = int(_option(entry, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval) if interval > 0 else None,
            always_update=True,
        )
        self.data = None

    @property
    def guard_state(self) -> GuardState:
        return self.guard.state

    async def async_load(self) -> None:
        await self.guard.load()

    @callback
    def _guard_changed(self, _state: GuardState) -> None:
        self.async_update_listeners()

    def _publish(self, snapshot: Snapshot) -> None:
        self.last_refresh = dt_util.utcnow()
        self.last_warning = snapshot.warning
        self.async_set_updated_data(snapshot)

    async def _async_update_data(self) -> Snapshot | None:
        try:
            snapshot = await self.session.poll()
        except ERRORS as err:
            # Transport errors may include proxy or address details; keep the message generic.
            raise UpdateFailed(
                "Bluetooth status query failed; check the proxy and that no other app is connected"
            ) from err
        self.last_refresh = dt_util.utcnow()
        self.last_warning = None
        return snapshot

    async def async_refresh_now(self) -> None:
        try:
            snapshot = await self.session.poll()
        except ERRORS as err:
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
            raise HomeAssistantError(
                "Command failed or unconfirmed; inspect the toilet before retrying"
            ) from err
        self._publish(snapshot)
        if snapshot.warning == FLUSH_UNCONFIRMED:
            _LOGGER.warning("Flush command sent but the flush flag was not observed")

    async def async_guard(self, suspend: bool) -> None:
        self._require_controls()
        try:
            snapshot = await (self.guard.suspend() if suspend else self.guard.resume())
        except CommandRefused as err:
            raise HomeAssistantError(str(err)) from err
        except ERRORS + (VerificationError,) as err:
            raise HomeAssistantError(
                "Shower guard change not confirmed; it will be retried by the next call"
            ) from err
        if snapshot is not None:
            self._publish(snapshot)
        else:
            self.async_update_listeners()

    async def async_manual_auto_cover(self, enabled: bool) -> None:
        """A manual switch change overrides the shower guard's remembered value."""
        await self.async_command(SetSettings({"auto_cover": enabled}))
        await self.guard.cancel()

    async def async_close(self) -> None:
        await self.async_shutdown()
        await self.session.close()
