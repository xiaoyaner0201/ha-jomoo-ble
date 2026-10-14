"""Shared device identity and strictly observed state projection."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL
from .lib.protocol import LID_RING, STATE, ProtocolError, mechanism, settings


class JomooEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.data['address']}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.data["address"])},
            manufacturer="JOMOO",
            model=MODEL,
            name="JOMOO ZS800J",
        )

    def frame(self, command):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.frames.get(command)

    def setting_values(self):
        frame = self.frame(STATE)
        if frame is None:
            return {}
        try:
            return settings(frame)
        except ProtocolError:
            return {}

    def mechanism_values(self):
        frame = self.frame(LID_RING)
        return mechanism(frame) if frame else None
