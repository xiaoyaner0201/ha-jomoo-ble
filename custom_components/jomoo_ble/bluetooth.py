"""Home Assistant Bluetooth routing, including connectable remote proxies."""

from __future__ import annotations

import asyncio

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import MODEL_CODE
from .lib.client import SessionError, SessionManager


def make_session(hass: HomeAssistant, address: str, prefix: str) -> SessionManager:
    async def connect():
        info = bluetooth.async_last_service_info(hass, address, connectable=True)
        device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
        if info is None or device is None:
            raise SessionError("No connectable Bluetooth advertisement")
        # A name match is model evidence, not authentication. Only this model's
        # wire profile is implemented. A generic JOMOO advert is insufficient.
        if not info.name.startswith(prefix) or not info.name.endswith("_" + MODEL_CODE):
            raise SessionError("Unsupported advertised model")
        return await asyncio.wait_for(
            establish_connection(
                BleakClientWithServiceCache,
                device,
                "JOMOO BLE",
                max_attempts=2,
                timeout=40,
                ble_device_callback=lambda: (
                    bluetooth.async_ble_device_from_address(hass, address, connectable=True)
                    or device
                ),
            ),
            timeout=120,
        )

    return SessionManager(connect)
