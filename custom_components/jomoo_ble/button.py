"""Refresh plus verified mechanical controls; flush completion is never assumed."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import JomooEntity
from .lib.client import Mechanical

VERIFIED = (
    Mechanical.OPEN_LID,
    Mechanical.CLOSE_LID,
    Mechanical.OPEN_RING,
    Mechanical.CLOSE_RING,
    Mechanical.SMALL_FLUSH,
)
EXPERIMENTAL = (Mechanical.LARGE_FLUSH,)
ICONS = {
    Mechanical.OPEN_LID: "mdi:toilet",
    Mechanical.CLOSE_LID: "mdi:toilet",
    Mechanical.OPEN_RING: "mdi:circle-outline",
    Mechanical.CLOSE_RING: "mdi:circle-off-outline",
    Mechanical.SMALL_FLUSH: "mdi:water",
    Mechanical.LARGE_FLUSH: "mdi:water-plus",
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [RefreshButton(coordinator, "refresh")]
    entities += [ActionButton(coordinator, action, False) for action in VERIFIED]
    entities += [ActionButton(coordinator, action, True) for action in EXPERIMENTAL]
    async_add_entities(entities)


class RefreshButton(JomooEntity, ButtonEntity):
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_now()


class ActionButton(JomooEntity, ButtonEntity):
    def __init__(self, coordinator, action: Mechanical, experimental: bool) -> None:
        super().__init__(coordinator, action.value)
        self.action = action
        self.experimental = experimental
        self._attr_icon = ICONS[action]
        self._attr_entity_registry_enabled_default = not experimental

    @property
    def available(self) -> bool:
        # State is read fresh inside the press, so no prior refresh is needed.
        if not super().available or not self.coordinator.controls_enabled:
            return False
        return self.coordinator.experimental_enabled or not self.experimental

    async def async_press(self) -> None:
        await self.coordinator.async_command(self.action, experimental=self.experimental)
