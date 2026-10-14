"""Ordinal settings plus unmapped/raw diagnostics; no invented temperature units."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import JomooEntity
from .lib.protocol import EXTENDED, FILTER, STATE, WORK

SETTINGS = {
    "water_temperature_level": "Water temperature level",
    "seat_temperature_level": "Seat temperature level",
    "air_temperature_level": "Air temperature level",
    "hip_water_pressure": "Hip water pressure level",
    "hip_nozzle_position": "Hip nozzle position",
    "woman_water_pressure": "Woman water pressure level",
    "woman_nozzle_position": "Woman nozzle position",
}
RAW = {
    STATE: "E2 raw status",
    FILTER: "Filter raw status",
    EXTENDED: "FA raw status",
    WORK: "E9 raw status",
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [SettingSensor(coordinator, k, n) for k, n in SETTINGS.items()]
        + [RawSensor(coordinator, k, n) for k, n in RAW.items()]
        + [WorkSensor(coordinator, "work_status", "Work status code")]
    )


class SettingSensor(JomooEntity, SensorEntity):
    def __init__(self, coordinator, key, name):
        super().__init__(coordinator, key, name)
        self.key = key

    @property
    def native_value(self):
        return self.setting_values().get(self.key)


class RawSensor(JomooEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, command, name):
        super().__init__(coordinator, f"raw_{command:02x}", name)
        self.command = command

    @property
    def native_value(self):
        frame = self.frame(self.command)
        return frame.payload.hex() if frame else None


class WorkSensor(JomooEntity, SensorEntity):
    @property
    def native_value(self):
        frame = self.frame(WORK)
        return frame.payload[3] if frame else None
