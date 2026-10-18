"""JOMOO ZS800J local Bluetooth integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, SERVICE_REFRESH
from .coordinator import JomooCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def refresh(call: ServiceCall) -> None:
        registry = dr.async_get(hass)
        entries = []
        for device_id in call.data["device_id"]:
            device = registry.async_get(device_id)
            if device is None:
                raise HomeAssistantError("Unknown device")
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is not None and entry.domain == DOMAIN and entry.runtime_data:
                    entries.append(entry)
        if not entries:
            raise HomeAssistantError("No loaded JOMOO BLE device selected")
        for entry in entries:
            await entry.runtime_data.async_refresh_now()

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        refresh,
        schema=vol.Schema({vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string])}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = JomooCoordinator(hass, entry)
    await coordinator.async_load()
    # No default startup BLE connection; persistent acquisition is explicit opt-in.
    entry.runtime_data = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if coordinator.stream_enabled:
            # Failure is caught by the coordinator; no setup-retry reconnection loop.
            await coordinator.async_refresh()
        elif coordinator.update_interval is not None:
            entry.async_create_background_task(
                hass, coordinator.async_refresh(), f"{DOMAIN}_first_refresh"
            )
    except BaseException:
        await coordinator.async_close()
        raise
    entry.async_on_unload(hass.bus.async_listen_once("homeassistant_stop", coordinator.async_stop))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Confirm physical release before removing diagnostics or allowing a reload.
    # A failed close raises and leaves this runtime blocked, not falsely unloaded.
    await entry.runtime_data.async_close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
