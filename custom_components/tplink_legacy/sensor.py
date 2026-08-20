"""Capteurs du routeur."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TpLinkLegacyConfigEntry
from .entity import TpLinkLegacyEntity


@dataclass(frozen=True, kw_only=True)
class TpLinkSensorDescription(SensorEntityDescription):
    """Description d'un capteur, avec sa fonction d'extraction."""

    value_fn: Callable[[dict[str, Any]], Any]


def _etat(status: dict[str, Any]) -> str:
    """Résume en un mot ce que le routeur a réellement livré au dernier relevé."""
    if status.get("errors"):
        return "partiel"
    if status.get("stale"):
        return "partiel"
    return "complet"


def _uptime(status: dict[str, Any]) -> datetime | None:
    seconds = (status.get("info") or {}).get("uptime")
    if seconds is None:
        return None
    return dt_util.utcnow() - timedelta(seconds=int(seconds))


SENSORS: tuple[TpLinkSensorDescription, ...] = (
    TpLinkSensorDescription(
        key="etat_donnees",
        translation_key="etat_donnees",
        device_class=SensorDeviceClass.ENUM,
        options=["complet", "partiel", "injoignable"],
        value_fn=_etat,
    ),
    TpLinkSensorDescription(
        key="clients",
        translation_key="clients",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="appareils",
        value_fn=lambda s: s.get("clientCount"),
    ),
    TpLinkSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_uptime,
    ),
    TpLinkSensorDescription(
        key="wan_ip",
        translation_key="wan_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (s.get("wan") or {}).get("ip"),
    ),
    TpLinkSensorDescription(
        key="wan_status",
        translation_key="wan_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (s.get("wan") or {}).get("status"),
    ),
    TpLinkSensorDescription(
        key="lan_ip",
        translation_key="lan_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (s.get("lan") or {}).get("ip"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TpLinkLegacyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        TpLinkLegacySensor(entry.runtime_data, description) for description in SENSORS
    )


class TpLinkLegacySensor(TpLinkLegacyEntity, SensorEntity):
    """Un capteur alimenté par l'instantané du coordinateur."""

    entity_description: TpLinkSensorDescription

    def __init__(self, coordinator, description: TpLinkSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        # Le capteur d'état doit rester lisible quand le routeur ne répond plus :
        # c'est précisément le moment où l'on veut le consulter.
        if self.entity_description.key == "etat_donnees":
            return True
        return super().available

    @property
    def native_value(self) -> Any:
        if self.entity_description.key == "etat_donnees" and not self.coordinator.last_update_success:
            return "injoignable"
        return self.entity_description.value_fn(self._status)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "etat_donnees":
            return None
        status = self._status
        return {
            "sections_refusees": sorted(status.get("errors") or {}) or None,
            "sections_non_rafraichies": status.get("stale") or None,
            "derniere_erreur": str(self.coordinator.last_exception)
            if self.coordinator.last_exception
            else None,
        }
