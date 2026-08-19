"""Coordinateur de rafraîchissement pour un routeur TP-Link legacy."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import TpLinkAuthError, TpLinkError, TpLinkRouter
from .const import (
    CONF_INCLUDE_SECRETS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_USERNAME,
    DOMAIN,
)

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

        seconds = entry.options.get(CONF_SCAN_INTERVAL)
        self._interval = (
            timedelta(seconds=int(seconds)) if seconds else DEFAULT_SCAN_INTERVAL
        )
        self._polling = True

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=self._interval,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        include_secrets = self.entry.options.get(CONF_INCLUDE_SECRETS, False)
        try:
            status = await self.router.get_status(include_secrets=include_secrets)
        except TpLinkAuthError as err:
            # Déclenche le formulaire de ré-authentification plutôt qu'une erreur muette.
            raise ConfigEntryAuthFailed(f"Authentification refusée : {err}") from err
        except TpLinkError as err:
            raise UpdateFailed(f"Routeur injoignable : {err}") from err

        # Ce firmware répond de façon intermittente : une section refusée ne
        # doit pas effacer ce qui a été lu correctement au relevé précédent,
        # sinon les entités clignotent entre leur valeur et « inconnu ».
        status = self._merge_with_previous(status)

        for client in status.get("clients") or []:
            if mac := client.get("mac"):
                self.known_clients.add(mac)

        # Des sections manquantes signalent presque toujours une éviction : le
        # firmware n'admet qu'un administrateur, et toute connexion — un
        # navigateur ouvert sur l'interface web — invalide celle de Home
        # Assistant en cours de lecture.
        errors = status.get("errors") or {}
        if errors and not self._warned_restricted:
            self._warned_restricted = True
            _LOGGER.warning(
                "Le routeur %s n'a pas renvoyé certaines sections (%s). "
                "Ce firmware n'accepte qu'un administrateur connecté à la fois : "
                "une session ouverte sur son interface web évince celle de Home "
                "Assistant. L'interrupteur « Interrogation du routeur » permet de "
                "suspendre les relevés le temps d'une intervention manuelle.",
                self.router.host,
                ", ".join(sorted(errors)),
            )
        elif not errors:
            self._warned_restricted = False

        return status

    #: Sections conservées d'un relevé à l'autre quand le routeur les refuse.
    _STICKY_SECTIONS = ("info", "lan", "wan", "wireless")

    def _merge_with_previous(self, status: dict[str, Any]) -> dict[str, Any]:
        """Complète les sections manquantes par la dernière valeur connue.

        Les entités concernées portent alors `stale` dans leurs attributs, pour
        que l'on sache que la valeur affichée n'a pas été rafraîchie.
        """
        previous = self.data or {}
        stale: list[str] = []

        for section in self._STICKY_SECTIONS:
            if status.get(section) is None and previous.get(section) is not None:
                status[section] = previous[section]
                stale.append(section)

        # Les clients, eux, ne sont pas conservés : un appareil parti doit
        # pouvoir devenir absent, c'est tout l'intérêt du suivi de présence.
        if stale:
            status["stale"] = stale
            status["clientCount"] = (
                status.get("clientCount")
                if isinstance(status.get("clients"), list)
                else previous.get("clientCount")
            )
        return status

    @property
    def polling(self) -> bool:
        """L'interrogation périodique est-elle active ?"""
        return self._polling

    def set_polling(self, enabled: bool) -> None:
        """Suspend ou reprend l'interrogation périodique.

        Le routeur n'accepte qu'un administrateur à la fois : chaque connexion
        invalide la précédente. Suspendre l'interrogation rend donc l'interface
        web utilisable sans que Home Assistant ne déconnecte l'utilisateur
        toutes les trente secondes — et inversement.

        Les données déjà lues restent exposées ; elles cessent simplement d'être
        rafraîchies.
        """
        if enabled == self._polling:
            return
        self._polling = enabled
        # Le setter de `update_interval` reprogramme (ou annule) la minuterie.
        self.update_interval = self._interval if enabled else None
        _LOGGER.debug(
            "Interrogation de %s %s",
            self.router.host,
            "reprise" if enabled else "suspendue",
        )

    async def async_release_session(self) -> None:
        """Ferme la session côté routeur pour libérer le slot administrateur."""
        await self.router.disconnect()

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
