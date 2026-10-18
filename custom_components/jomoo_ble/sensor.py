"""Read-only sensors decoded from the latest on-demand status read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.helpers.entity import EntityCategory

from .entity import JomooEntity
from .lib.protocol import EXTENDED, FILTER, LID_RING, STATE, WORK, WorkStatus


@dataclass(frozen=True)
class Spec:
    value: Callable[[Any], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    category: EntityCategory | None = None
    icon: str | None = None
    options: list[str] | None = None


def _field(record: str, name: str):
    def get(snapshot):
        value = getattr(snapshot, record)
        return None if value is None else getattr(value, name)

    return get


SENSORS: dict[str, Spec] = {
    "filter_remaining": Spec(
        lambda s: s.filter.remaining_percent if s.filter else None,
        PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
    ),
    "filter_used": Spec(
        lambda s: s.filter.used_hours if s.filter else None,
        UnitOfTime.HOURS,
        SensorDeviceClass.DURATION,
        SensorStateClass.TOTAL_INCREASING,
        EntityCategory.DIAGNOSTIC,
    ),
    "work_status": Spec(
        lambda s: s.runtime.status.value if s.runtime else None,
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in WorkStatus],
        icon="mdi:state-machine",
    ),
    "lady_pressure": Spec(_field("settings", "lady_pressure"), icon="mdi:gauge"),
    "lady_nozzle": Spec(_field("settings", "lady_nozzle"), icon="mdi:arrow-left-right"),
}
RAW = {
    "raw_e2": STATE,
    "raw_fa": EXTENDED,
    "raw_e9": WORK,
    "raw_ea": LID_RING,
    "raw_e7": FILTER,
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [SpecSensor(coordinator, k, v) for k, v in SENSORS.items()]
    entities.append(LastRefreshSensor(coordinator, "last_refresh"))
    if coordinator.stream_enabled:
        entities.append(LastReceivedSensor(coordinator, "last_status_received"))
    entities += [RawSensor(coordinator, key, command) for key, command in RAW.items()]
    async_add_entities(entities)


class SpecSensor(JomooEntity, SensorEntity):
    def __init__(self, coordinator, key: str, spec: Spec) -> None:
        super().__init__(coordinator, key)
        self.spec = spec
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_entity_category = spec.category
        self._attr_icon = spec.icon
        self._attr_options = spec.options

    @property
    def native_value(self):
        return None if self.snapshot is None else self.spec.value(self.snapshot)


class LastRefreshSensor(JomooEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self.coordinator.last_refresh


class LastReceivedSensor(JomooEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self):
        return self.coordinator.last_received

    @property
    def extra_state_attributes(self):
        snapshot = self.snapshot
        return {
            "live": self.coordinator.session.stream_connected,
            "frame_received_at": {
                f"0x{command:02X}": value.isoformat()
                for command, value in (snapshot.received_at.items() if snapshot else [])
            },
        }


class RawSensor(JomooEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, key: str, command: int) -> None:
        super().__init__(coordinator, key)
        self.command = command

    @property
    def native_value(self):
        if self.snapshot is None:
            return None
        frame = self.snapshot.frames.get(self.command)
        return None if frame is None else frame.payload.hex()
