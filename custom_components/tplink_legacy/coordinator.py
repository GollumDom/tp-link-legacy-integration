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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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

#: Plafond du recul entre deux relevés après des échecs répétés. Le httpd de ces
#: routeurs ne tient qu'une poignée de sockets : insister toutes les trente
#: secondes sur un routeur qui ne répond plus l'achève au lieu de le réveiller.
MAX_BACKOFF = timedelta(minutes=10)

#: Tolérance sur l'horodatage de démarrage. Le firmware compte en secondes
#: entières et l'aller-retour réseau varie : sans marge, « Démarré le » oscille
#: d'une seconde à chaque relevé et sature l'historique.
BOOT_TIME_DRIFT = timedelta(seconds=5)


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
        self._failures = 0

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
        try:
            status = await self._async_read_router()
        except Exception:
            self._back_off()
            raise
        self._back_off(recovered=True)
        return status

    def _back_off(self, *, recovered: bool = False) -> None:
        """Espace les relevés tant que le routeur ne répond pas.

        Ces firmwares ne se contentent pas d'échouer : à force de connexions,
        leur httpd cesse de répondre à quiconque, et seul un redémarrage le
        remet en marche. Reculer, c'est lui laisser une chance de revenir.
        """
        if recovered:
            if self._failures:
                self._failures = 0
                if self._polling:
                    self.update_interval = self._interval
            return

        self._failures += 1
        interval = min(self._interval * 2 ** min(self._failures, 6), MAX_BACKOFF)
        if self._polling and interval != self.update_interval:
            self.update_interval = interval
            _LOGGER.debug(
                "Routeur %s muet depuis %d relevés : prochain essai dans %s",
                self.router.host,
                self._failures,
                interval,
            )

    async def _async_read_router(self) -> dict[str, Any]:
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
        self._sync_repair_issue(errors)

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

    @property
    def _issue_id(self) -> str:
        return f"restricted_{self.entry.entry_id}"

    def _sync_repair_issue(self, errors: dict[str, Any]) -> None:
        """Fait remonter le refus du routeur dans « Paramètres → Réparations ».

        Un simple message de journal passe inaperçu : tant que le routeur ne
        livre qu'une partie des données, l'utilisateur doit le voir, avec
        l'explication et la marche à suivre.
        """
        if errors:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="restricted",
                translation_placeholders={
                    "host": self.router.host,
                    "sections": ", ".join(sorted(errors)),
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

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

        status["bootTime"] = self._boot_time(status, previous, stale)

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

    @staticmethod
    def _boot_time(
        status: dict[str, Any], previous: dict[str, Any], stale: list[str]
    ) -> Any:
        """Instant de démarrage du routeur, figé tant qu'il n'est pas relu.

        Le firmware donne une durée de fonctionnement, pas une date : la date se
        calcule par différence avec l'heure courante. Refaire ce calcul sur une
        durée conservée du relevé précédent ferait avancer l'instant de démarrage
        au rythme de l'horloge — le routeur paraîtrait redémarrer sans cesse.
        """
        previous_boot = previous.get("bootTime")
        uptime = (status.get("info") or {}).get("uptime")
        if uptime is None or "info" in stale:
            return previous_boot

        boot = dt_util.utcnow() - timedelta(seconds=int(uptime))
        if previous_boot is not None and abs(boot - previous_boot) <= BOOT_TIME_DRIFT:
            return previous_boot
        return boot

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
        # Reprendre repart d'un intervalle normal : le recul accumulé décrivait
        # un routeur qu'on ne sollicitait plus.
        self._failures = 0
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
