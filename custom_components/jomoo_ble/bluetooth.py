"""Home Assistant Bluetooth routing, including connectable ESPHome proxies."""

from __future__ import annotations

import asyncio

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import MODEL_CODE
from .lib.client import SessionError, SessionManager


def supported_name(name: str | None, prefix: str) -> bool:
    """A name match is model evidence, not authentication."""
    return bool(name) and name.startswith(prefix) and name.endswith("_" + MODEL_CODE)


def make_session(hass: HomeAssistant, address: str, prefix: str) -> SessionManager:
    async def connect():
        info = bluetooth.async_last_service_info(hass, address, connectable=True)
        device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
        if info is None or device is None:
            raise SessionError("No connectable Bluetooth advertisement for this toilet")
        if not supported_name(info.name, prefix):
            raise SessionError("Unsupported advertised model")
        return await asyncio.wait_for(
            establish_connection(
                BleakClientWithServiceCache,
                device,
                "JOMOO BLE",
                max_attempts=2,
                disconnected_callback=lambda client: session.connection_lost(client),
                ble_device_callback=lambda: (
                    bluetooth.async_ble_device_from_address(hass, address, connectable=True)
                    or device
                ),
            ),
            timeout=90,
        )

    session = SessionManager(connect)
    return session
