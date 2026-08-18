"""Interrupteurs : activation des radios Wi-Fi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TpLinkLegacyConfigEntry
from .entity import TpLinkLegacyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TpLinkLegacyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    radios = (coordinator.data or {}).get("wireless") or []
    # Une entité par bande : c'est la clé stable pour retrouver la radio d'un
    # rafraîchissement à l'autre (l'ordre de la liste ne l'est pas).
    async_add_entities(
        TpLinkLegacyWirelessSwitch(coordinator, radio["band"])
        for radio in radios
        if radio.get("band")
    )


class TpLinkLegacyWirelessSwitch(TpLinkLegacyEntity, SwitchEntity):
    """Allume ou éteint une radio Wi-Fi."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "wireless"

    def __init__(self, coordinator, band: str) -> None:
        super().__init__(coordinator, f"wireless_{band}")
        self._band = band
        self._attr_translation_placeholders = {"band": band}

    @property
    def _radio(self) -> dict[str, Any] | None:
        for radio in self._status.get("wireless") or []:
            if radio.get("band") == self._band:
                return radio
        return None

    @property
    def available(self) -> bool:
        return super().available and self._radio is not None

    @property
    def is_on(self) -> bool | None:
        radio = self._radio
        return None if radio is None else bool(radio.get("enabled"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        radio = self._radio
        if radio is None:
            return None
        return {
            "ssid": radio.get("ssid"),
            "bssid": radio.get("bssid"),
            "channel": radio.get("channel"),
            "bandwidth": radio.get("bandwidth"),
            "security": (radio.get("security") or {}).get("mode"),
            "hidden": radio.get("hidden"),
        }

    async def _async_set(self, enabled: bool) -> None:
        await self.coordinator.router.set_wireless_enabled(enabled, band=self._band)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
