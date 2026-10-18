"""Lid/ring position and motion, occupancy, flushing, faults and shower-guard state."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import EntityCategory

from .entity import JomooEntity
from .lib.protocol import FoamLevel


def _get(record: str, name: str) -> Callable[[Any], Any]:
    def get(snapshot):
        value = getattr(snapshot, record)
        return None if value is None else getattr(value, name)

    return get


def _foam_low(snapshot):
    extended = snapshot.extended
    if extended is None or extended.foam_level is FoamLevel.UNKNOWN:
        return None
    return extended.foam_level is FoamLevel.LOW


# key -> (getter, device class, entity category)
SENSORS = {
    "lid_open": (_get("mechanism", "lid_open"), BinarySensorDeviceClass.OPENING, None),
    "ring_open": (_get("mechanism", "ring_open"), BinarySensorDeviceClass.OPENING, None),
    "lid_moving": (_get("mechanism", "lid_moving"), BinarySensorDeviceClass.MOVING, None),
    "ring_moving": (_get("mechanism", "ring_moving"), BinarySensorDeviceClass.MOVING, None),
    "seated": (_get("runtime", "seated"), BinarySensorDeviceClass.OCCUPANCY, None),
    "flushing": (_get("extended", "flushing"), BinarySensorDeviceClass.RUNNING, None),
    "water_shortage": (
        _get("runtime", "water_shortage"),
        BinarySensorDeviceClass.PROBLEM,
        EntityCategory.DIAGNOSTIC,
    ),
    "flow_abnormal": (
        _get("runtime", "flow_abnormal"),
        BinarySensorDeviceClass.PROBLEM,
        EntityCategory.DIAGNOSTIC,
    ),
    "sensor_fault": (
        _get("runtime", "fault"),
        BinarySensorDeviceClass.PROBLEM,
        EntityCategory.DIAGNOSTIC,
    ),
    "filter_low": (
        _get("extended", "filter_insufficient"),
        BinarySensorDeviceClass.PROBLEM,
        None,
    ),
    "foam_low": (_foam_low, BinarySensorDeviceClass.PROBLEM, None),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        StatusBinarySensor(coordinator, key, *spec) for key, spec in SENSORS.items()
    ]
    entities.append(GuardBinarySensor(coordinator, "guard_active"))
    if coordinator.stream_enabled:
        entities.append(StreamConnectedSensor(coordinator, "status_stream_connected"))
    async_add_entities(entities)


class StatusBinarySensor(JomooEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, getter, device_class, category) -> None:
        super().__init__(coordinator, key)
        self.getter = getter
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool | None:
        return None if self.snapshot is None else self.getter(self.snapshot)


class StreamConnectedSensor(JomooEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.session.stream_connected

    @property
    def extra_state_attributes(self):
        return {
            "status": "live" if self.is_on else self.coordinator.stream_error,
            "disconnect_uncertain": self.coordinator.session.blocked,
            "recovery": (
                "Check Bluetooth release, then restart HA"
                if self.coordinator.session.blocked
                else "Refresh status manually; no automatic reconnect"
            ),
        }


class GuardBinarySensor(JomooEntity, BinarySensorEntity):
    _attr_icon = "mdi:shower-head"

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        state = self.coordinator.guard_state
        return state.active or state.pending
