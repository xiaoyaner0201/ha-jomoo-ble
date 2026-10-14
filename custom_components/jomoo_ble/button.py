"""Verified mechanical controls; flush completion is not inferred from write success."""

from homeassistant.components.button import ButtonEntity

from .entity import JomooEntity
from .lib.protocol import Action

ACTIONS = {
    Action.OPEN_LID: "Open lid",
    Action.CLOSE_LID: "Close lid",
    Action.OPEN_RING: "Open seat ring",
    Action.CLOSE_RING: "Close seat ring",
    Action.SMALL_FLUSH: "Small flush",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ActionButton(entry.runtime_data, a, n) for a, n in ACTIONS.items()])


class ActionButton(JomooEntity, ButtonEntity):
    def __init__(self, coordinator, action, name):
        super().__init__(coordinator, action.value, name)
        self.action = action

    @property
    def available(self):
        state = self.mechanism_values()
        return (
            super().available
            and self.coordinator.controls_enabled
            and bool(self.setting_values())
            and state is not None
            and state.lid_open is not None
            and state.ring_open is not None
            and not state.lid_moving
            and not state.ring_moving
        )

    async def async_press(self):
        await self.coordinator.async_command(self.action)
