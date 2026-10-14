"""Only the physically validated automatic-cover setting is writable."""

from homeassistant.components.switch import SwitchEntity

from .entity import JomooEntity
from .lib.protocol import Action


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AutoCoverSwitch(entry.runtime_data, "auto_cover", "Automatic cover")])


class AutoCoverSwitch(JomooEntity, SwitchEntity):
    @property
    def is_on(self):
        return self.setting_values().get("auto_cover")

    @property
    def available(self):
        return (
            super().available and self.coordinator.controls_enabled and bool(self.setting_values())
        )

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_command(Action.AUTO_COVER_ON)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_command(Action.AUTO_COVER_OFF)
