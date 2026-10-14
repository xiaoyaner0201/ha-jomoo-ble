"""Automatic lid opening (verified, with shower guard) and experimental options."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import EntityCategory

from .const import SERVICE_RESUME, SERVICE_SUSPEND
from .entity import JomooEntity
from .lib.client import SetOption, SetSettings
from .lib.protocol import Option

# key -> (source record, attribute, command factory)
EXPERIMENTAL = {
    "auto_flush": ("settings", "auto_flush", lambda on: SetSettings({"auto_flush": on})),
    "auto_night_light": (
        "settings",
        "auto_night_light",
        lambda on: SetSettings({"auto_night_light": on}),
    ),
    "uv_disinfection": (
        "extended",
        "uv_disinfection",
        lambda on: SetOption(Option.UV_DISINFECTION, on),
    ),
    "close_lid_before_flush": (
        "extended",
        "close_lid_before_flush",
        lambda on: SetOption(Option.CLOSE_LID_BEFORE_FLUSH, on),
    ),
    "auto_small_flush": (
        "extended",
        "auto_small_flush",
        lambda on: SetOption(Option.AUTO_SMALL_FLUSH, on),
    ),
    "foot_sensor": ("extended", "foot_sensor", lambda on: SetOption(Option.FOOT_SENSOR, on)),
    "ambient_light": (
        "extended",
        "ambient_light",
        lambda on: SetOption(Option.AMBIENT_LIGHT, on),
    ),
}


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [AutoCoverSwitch(coordinator, "auto_cover")]
    entities += [ExperimentalSwitch(coordinator, key) for key in EXPERIMENTAL]
    async_add_entities(entities)
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_SUSPEND, None, "async_suspend")
    platform.async_register_entity_service(SERVICE_RESUME, None, "async_resume")


class AutoCoverSwitch(JomooEntity, SwitchEntity):
    _attr_icon = "mdi:toilet"

    @property
    def is_on(self) -> bool | None:
        settings = self.snapshot.settings if self.snapshot else None
        return None if settings is None else settings.auto_cover

    @property
    def extra_state_attributes(self) -> dict:
        state = self.coordinator.guard_state
        return {
            "guard_active": state.active,
            "guard_pending": state.pending,
            "guard_previous": state.previous,
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_manual_auto_cover(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_manual_auto_cover(False)

    async def async_suspend(self) -> None:
        await self.coordinator.async_guard(suspend=True)

    async def async_resume(self) -> None:
        await self.coordinator.async_guard(suspend=False)


class ExperimentalSwitch(JomooEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.source, self.attribute, self.factory = EXPERIMENTAL[key]

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.controls_enabled
            and self.coordinator.experimental_enabled
        )

    @property
    def is_on(self) -> bool | None:
        if self.snapshot is None:
            return None
        record = getattr(self.snapshot, self.source)
        return None if record is None else getattr(record, self.attribute)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_command(self.factory(True), experimental=True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_command(self.factory(False), experimental=True)
