"""Verified device settings and opt-in experimental options."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .entity import JomooEntity
from .lib.client import SetOption, SetSettings
from .lib.protocol import Option

# key -> (source record, attribute, command factory)
VERIFIED = {
    "auto_cover": ("settings", "auto_cover", lambda on: SetSettings({"auto_cover": on})),
    "foot_sensor": ("extended", "foot_sensor", lambda on: SetOption(Option.FOOT_SENSOR, on)),
}
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
    "ambient_light": (
        "extended",
        "ambient_light",
        lambda on: SetOption(Option.AMBIENT_LIGHT, on),
    ),
}


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [SettingSwitch(coordinator, key) for key in VERIFIED]
    entities += [SettingSwitch(coordinator, key, experimental=True) for key in EXPERIMENTAL]
    async_add_entities(entities)


class SettingSwitch(JomooEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str, *, experimental: bool = False) -> None:
        super().__init__(coordinator, key)
        self.experimental = experimental
        self._attr_entity_registry_enabled_default = not experimental
        self._attr_icon = "mdi:foot-print" if key == "foot_sensor" else "mdi:toilet"
        self.source, self.attribute, self.factory = (EXPERIMENTAL if experimental else VERIFIED)[
            key
        ]

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.controls_enabled
            and (not self.experimental or self.coordinator.experimental_enabled)
        )

    @property
    def is_on(self) -> bool | None:
        if self.snapshot is None:
            return None
        record = getattr(self.snapshot, self.source)
        return None if record is None else getattr(record, self.attribute)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_command(self.factory(True), experimental=self.experimental)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_command(self.factory(False), experimental=self.experimental)
