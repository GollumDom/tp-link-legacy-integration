"""Coordinateur de rafraîchissement pour un routeur TP-Link legacy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TpLinkAuthError, TpLinkError, TpLinkRouter
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_TIMEOUT, DEFAULT_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class TpLinkLegacyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Interroge le routeur et partage l'instantané entre toutes les entités.

    Le httpd du routeur ne traite qu'une requête à la fois et n'accepte qu'un
    administrateur : un coordinateur unique par routeur évite de le saturer.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.router = TpLinkRouter(
            host=entry.data[CONF_HOST],
            password=entry.data[CONF_PASSWORD],
            username=entry.data.get(CONF_USERNAME, DEFAULT_USERNAME),
            timeout=DEFAULT_TIMEOUT,
        )
        # Adresses MAC vues au moins une fois : un appareil qui disparaît doit
        # devenir « absent », pas cesser d'exister.
        self.known_clients: set[str] = set()
        self._warned_restricted = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.router.get_status()
        except TpLinkAuthError as err:
            raise UpdateFailed(f"Authentification refusée : {err}") from err
        except TpLinkError as err:
            raise UpdateFailed(f"Routeur injoignable : {err}") from err

        for client in status.get("clients") or []:
            if mac := client.get("mac"):
                self.known_clients.add(mac)

        # Le firmware refuse les données personnelles à un client hors LAN :
        # on le signale une fois plutôt que de laisser des entités vides.
        errors = status.get("errors") or {}
        if errors and not self._warned_restricted:
            self._warned_restricted = True
            _LOGGER.warning(
                "Le routeur %s refuse une partie des données (%s). "
                "Ce firmware ne les expose qu'à un client du même réseau local : "
                "Home Assistant doit être sur le LAN du routeur.",
                self.router.host,
                ", ".join(sorted(errors)),
            )

        return status

    def clients_by_mac(self) -> dict[str, dict[str, Any]]:
        """Instantané des clients, indexé par adresse MAC."""
        return {
            client["mac"]: client
            for client in (self.data or {}).get("clients") or []
            if client.get("mac")
        }

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.router.disconnect()
