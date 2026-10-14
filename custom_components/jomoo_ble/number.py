"""Experimental level settings (unit-less device levels, not temperatures)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity import EntityCategory

from .entity import JomooEntity
from .lib.client import SetSettings
from .lib.protocol import RANGES

LEVELS = {
    "water_temperature": "mdi:water-thermometer",
    "seat_temperature": "mdi:seat",
    "air_temperature": "mdi:fan",
    "hip_pressure": "mdi:gauge",
    "hip_nozzle": "mdi:arrow-left-right",
    "wind_speed": "mdi:weather-windy",
    "wide_wash_level": "mdi:arrow-expand-horizontal",
}
EXTENDED_ONLY = {"wind_speed", "wide_wash_level"}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(LevelNumber(entry.runtime_data, key) for key in LEVELS)


class LevelNumber(JomooEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._attr_icon = LEVELS[key]
        low, high = RANGES[key]
        self._attr_native_min_value = low
        self._attr_native_max_value = high

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.controls_enabled
            and self.coordinator.experimental_enabled
        )

    @property
    def native_value(self) -> float | None:
        if self.snapshot is None:
            return None
        record = self.snapshot.extended if self.key in EXTENDED_ONLY else self.snapshot.settings
        return None if record is None else getattr(record, self.key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_command(
            SetSettings({self.key: int(round(value))}), experimental=True
        )
