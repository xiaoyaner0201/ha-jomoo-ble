"""Observed lid/ring positions and motion; unknown position is not closed."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import JomooEntity

MECHANISM = {
    "lid_open": "Lid open",
    "ring_open": "Seat ring open",
    "lid_moving": "Lid moving",
    "ring_moving": "Seat ring moving",
}


async def async_setup_entry(hass, entry, async_add_entities):
    co = entry.runtime_data
    async_add_entities(
        [MechanismSensor(co, k, n) for k, n in MECHANISM.items()]
        + [
            AutoFlushSensor(co, "auto_flush", "Automatic flush setting"),
            SafeProfileSensor(co, "safe_parameters", "Verified parameter profile"),
        ]
    )


class MechanismSensor(JomooEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, name):
        super().__init__(coordinator, key, name)
        self.key = key
        if key.endswith("open"):
            self._attr_device_class = BinarySensorDeviceClass.OPENING

    @property
    def is_on(self):
        state = self.mechanism_values()
        return getattr(state, self.key) if state else None


class AutoFlushSensor(JomooEntity, BinarySensorEntity):
    @property
    def is_on(self):
        return self.setting_values().get("auto_flush")


class SafeProfileSensor(JomooEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        return bool(self.setting_values())
