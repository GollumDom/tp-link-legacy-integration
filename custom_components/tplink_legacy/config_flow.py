"""Assistant de configuration : détection, saisie manuelle, options."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import TpLinkAuthError, TpLinkError, TpLinkRouter
from .const import (
    CONF_INCLUDE_SECRETS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_USERNAME,
    DOMAIN,
    MANUAL_HOST,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .discovery import discover

_LOGGER = logging.getLogger(__name__)

PASSWORD_FIELD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _credentials_schema(host: str | None) -> vol.Schema:
    """Formulaire d'identifiants, l'hôte étant figé s'il vient de la détection."""
    fields: dict[Any, Any] = {}
    if host is None:
        fields[vol.Required(CONF_HOST)] = cv.string
    fields[vol.Required(CONF_PASSWORD)] = PASSWORD_FIELD
    fields[vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME)] = cv.string
    return vol.Schema(fields)


class TpLinkLegacyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ajout d'un routeur : on vérifie l'accès avant de créer l'entrée."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return TpLinkLegacyOptionsFlow()

    # ------------------------------------------------------------ détection --

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Propose les routeurs détectés, ou bascule sur la saisie manuelle."""
        if user_input is not None:
            host = user_input[CONF_HOST]
            if host == MANUAL_HOST:
                return await self.async_step_manual()
            self._host = host
            return await self.async_step_credentials()

        try:
            found = await discover()
        except Exception:  # noqa: BLE001 — la détection ne doit jamais bloquer l'ajout
            _LOGGER.debug("Détection en échec", exc_info=True)
            found = []

        configured = {entry.data.get(CONF_HOST) for entry in self._async_current_entries()}
        candidates = [item["host"] for item in found if item["host"] not in configured]

        if not candidates:
            return await self.async_step_manual()

        options = [
            {"value": host, "label": host} for host in candidates
        ] + [{"value": MANUAL_HOST, "label": "Autre adresse…"}]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=candidates[0]): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
            description_placeholders={"count": str(len(candidates))},
        )

    # -------------------------------------------------------------- saisie --

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Saisie complète, hôte compris."""
        return await self._async_collect(user_input, step_id="manual", host=None)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Identifiants pour un routeur déjà détecté."""
        return await self._async_collect(user_input, step_id="credentials", host=self._host)

    async def _async_collect(
        self,
        user_input: dict[str, Any] | None,
        *,
        step_id: str,
        host: str | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**user_input}
            if host is not None:
                data[CONF_HOST] = host

            self._async_abort_entries_match({CONF_HOST: data[CONF_HOST]})
            info, error = await _async_validate(data)

            if error is None:
                await self.async_set_unique_id(info.get("mac") or data[CONF_HOST])
                self._abort_if_unique_id_configured(updates={CONF_HOST: data[CONF_HOST]})
                title = info.get("model") or data[CONF_HOST]
                return self.async_create_entry(
                    title=f"{title} ({data[CONF_HOST]})", data=data
                )
            errors["base"] = error

        return self.async_show_form(
            step_id=step_id,
            data_schema=_credentials_schema(host),
            errors=errors,
            description_placeholders={"host": host or ""},
        )

    # ---------------------------------------------------- ré-authentification --

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Le mot de passe du routeur a changé : on le remplace sans tout refaire."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            data = {**entry.data, **user_input}
            _, error = await _async_validate(data)
            if error is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_FIELD}),
            errors=errors,
            description_placeholders={"host": self._host or ""},
        )


async def _async_validate(data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Teste l'accès et renvoie ``(infos, code d'erreur)``."""
    router = TpLinkRouter(
        host=data[CONF_HOST],
        password=data[CONF_PASSWORD],
        username=data.get(CONF_USERNAME, DEFAULT_USERNAME),
        timeout=DEFAULT_TIMEOUT,
    )
    try:
        return await router.get_info(), None
    except TpLinkAuthError:
        return {}, "invalid_auth"
    except TpLinkError:
        return {}, "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Erreur inattendue en validant %s", data[CONF_HOST])
        return {}, "unknown"
    finally:
        await router.disconnect()


class TpLinkLegacyOptionsFlow(OptionsFlow):
    """Fréquence d'interrogation et exposition de la clé Wi-Fi."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(
                            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=5,
                            unit_of_measurement="s",
                            # Saisie directe plutôt qu'un curseur : l'échelle va
                            # de dix secondes à une heure, un curseur ne permet
                            # plus d'y viser une valeur.
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_INCLUDE_SECRETS,
                        default=options.get(CONF_INCLUDE_SECRETS, False),
                    ): cv.boolean,
                }
            ),
        )
