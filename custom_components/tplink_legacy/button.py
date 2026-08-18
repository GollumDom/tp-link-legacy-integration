"""Bouton de redémarrage du routeur."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TpLinkLegacyConfigEntry
from .entity import TpLinkLegacyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TpLinkLegacyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TpLinkLegacyRebootButton(entry.runtime_data)])


class TpLinkLegacyRebootButton(TpLinkLegacyEntity, ButtonEntity):
    """Redémarre le routeur."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reboot"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "reboot")

    async def async_press(self) -> None:
        await self.coordinator.router.reboot()
