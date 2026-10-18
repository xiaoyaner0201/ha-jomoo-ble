"""Shared device identity and decoded-state helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import JomooCoordinator


class JomooEntity(CoordinatorEntity[JomooCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: JomooCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"{MANUFACTURER} {MODEL}",
        )

    @property
    def available(self) -> bool:
        # Data is fetched on demand; an unknown state is shown as unknown, not unavailable.
        return not self.coordinator.session.blocked and (
            not self.coordinator.stream_enabled or self.coordinator.session.stream_connected
        )

    @property
    def snapshot(self):
        return self.coordinator.data
