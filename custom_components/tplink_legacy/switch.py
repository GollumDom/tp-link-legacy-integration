"""Interrupteurs : activation des radios Wi-Fi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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
    entities: list[SwitchEntity] = [TpLinkLegacyPollingSwitch(coordinator)]
    entities += [
        TpLinkLegacyWirelessSwitch(coordinator, radio["band"])
        for radio in radios
        if radio.get("band")
    ]
    async_add_entities(entities)


class TpLinkLegacyPollingSwitch(TpLinkLegacyEntity, SwitchEntity, RestoreEntity):
    """Suspend l'interrogation du routeur.

    Ces firmwares n'admettent qu'un administrateur connecté à la fois : tant que
    Home Assistant interroge le routeur, l'interface web se fait déconnecter, et
    réciproquement. Éteindre cet interrupteur libère le routeur le temps d'une
    intervention manuelle.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "polling"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "polling")

    @property
    def available(self) -> bool:
        # Doit rester manipulable même quand le routeur ne répond plus :
        # c'est justement l'interrupteur qui permet de le laisser tranquille.
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.polling

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Une suspension décidée par l'utilisateur doit survivre à un redémarrage.
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == STATE_OFF:
            self.coordinator.set_polling(False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.set_polling(True)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.set_polling(False)
        # Libère le slot administrateur immédiatement, sans attendre l'expiration.
        await self.coordinator.async_release_session()
        self.async_write_ha_state()


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
        if self.coordinator.polling:
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
