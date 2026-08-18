"""Capteur binaire : état de la connexion Internet."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TpLinkLegacyConfigEntry
from .entity import TpLinkLegacyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TpLinkLegacyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TpLinkLegacyWanSensor(entry.runtime_data)])


class TpLinkLegacyWanSensor(TpLinkLegacyEntity, BinarySensorEntity):
    """Vrai lorsque le WAN est connecté."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "wan"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "wan_connected")

    @property
    def is_on(self) -> bool | None:
        wan = self._status.get("wan")
        if wan is None:
            return None
        return bool(wan.get("connected"))
