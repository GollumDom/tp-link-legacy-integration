"""Suivi de présence des appareils connectés au routeur."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TpLinkLegacyConfigEntry
from .coordinator import TpLinkLegacyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TpLinkLegacyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée une entité par appareil vu, y compris ceux découverts plus tard."""
    coordinator = entry.runtime_data
    tracked: set[str] = set()

    @callback
    def _add_new_clients() -> None:
        new = coordinator.known_clients - tracked
        if not new:
            return
        tracked.update(new)
        async_add_entities(
            TpLinkLegacyDeviceTracker(coordinator, mac) for mac in sorted(new)
        )

    _add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_clients))


class TpLinkLegacyDeviceTracker(ScannerEntity):
    """Présent tant que le routeur voit l'appareil."""

    _attr_should_poll = False

    def __init__(self, coordinator: TpLinkLegacyCoordinator, mac: str) -> None:
        self.coordinator = coordinator
        self._mac = mac
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{mac}"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def _client(self) -> dict[str, Any] | None:
        return self.coordinator.clients_by_mac().get(self._mac)

    @property
    def name(self) -> str | None:
        client = self._client
        return (client or {}).get("hostname") or self._mac

    @property
    def source_type(self) -> SourceType:
        return SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def ip_address(self) -> str | None:
        return (self._client or {}).get("ip")

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def hostname(self) -> str | None:
        return (self._client or {}).get("hostname")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        client = self._client
        if client is None:
            return None
        return {
            "connection": client.get("connection"),
            "interface": client.get("interface"),
            "router": self.coordinator.router.host,
        }
