"""Intégration Home Assistant pour les routeurs TP-Link « legacy »."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import TpLinkLegacyCoordinator

type TpLinkLegacyConfigEntry = ConfigEntry[TpLinkLegacyCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TpLinkLegacyConfigEntry) -> bool:
    """Met en place un routeur."""
    coordinator = TpLinkLegacyCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TpLinkLegacyConfigEntry) -> bool:
    """Retire un routeur et libère sa session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: TpLinkLegacyConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
