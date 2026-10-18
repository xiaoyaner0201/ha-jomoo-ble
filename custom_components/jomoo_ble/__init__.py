"""JOMOO ZS800J local Bluetooth integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SERVICE_REFRESH, STORAGE_VERSION
from .coordinator import JomooCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_LOGGER = logging.getLogger(__name__)


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
    await _async_remove_legacy_guard(hass, entry, warn=True)
    registry = er.async_get(hass)
    stale_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.data['address']}_guard_active"
    )
    if stale_id is not None and registry.async_get(stale_id).config_entry_id == entry.entry_id:
        registry.async_remove(stale_id)
    foot_id = registry.async_get_entity_id("switch", DOMAIN, f"{entry.data['address']}_foot_sensor")
    if foot_id is not None:
        foot = registry.async_get(foot_id)
        # Upgrade the old integration default, never a user's explicit choice or ID.
        if (
            foot.config_entry_id == entry.entry_id
            and foot.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        ):
            registry.async_update_entity(foot_id, disabled_by=None)
    coordinator = JomooCoordinator(hass, entry)
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


async def _async_remove_legacy_guard(
    hass: HomeAssistant, entry: ConfigEntry, *, warn: bool = False
) -> None:
    """Discard pre-0.4 policy memory without connecting or restoring the device."""
    store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.guard")
    if warn:
        try:
            data = await store.async_load()
            if isinstance(data, dict) and (data.get("active") or data.get("pending")):
                _LOGGER.warning(
                    "The previous shower guard had suspended automatic lid opening; "
                    "check the Automatic lid opening switch, because this version "
                    "no longer restores it automatically"
                )
        except Exception:
            # Obsolete or unreadable policy memory must never prevent device setup.
            _LOGGER.debug("Could not read obsolete shower guard storage")
    try:
        await store.async_remove()
    except Exception:
        _LOGGER.debug("Could not remove obsolete shower guard storage")


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await _async_remove_legacy_guard(hass, entry)
