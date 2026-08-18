"""Base commune aux entités TP-Link legacy."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import TpLinkLegacyCoordinator


class TpLinkLegacyEntity(CoordinatorEntity[TpLinkLegacyCoordinator]):
    """Entité rattachée au routeur, avec ses informations d'appareil."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TpLinkLegacyCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"

    @property
    def _status(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def device_info(self) -> DeviceInfo:
        info = self._status.get("info") or {}
        lan = self._status.get("lan") or {}
        mac = info.get("mac") or lan.get("mac")

        device = DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            manufacturer=MANUFACTURER,
            name=self.coordinator.entry.title,
            model=info.get("model"),
            sw_version=info.get("firmware"),
            hw_version=info.get("hardware"),
            configuration_url=f"http://{self.coordinator.router.host}/",
        )
        if mac:
            device["connections"] = {("mac", mac.lower())}
        return device
