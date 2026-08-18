"""Assistant de configuration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import config_validation as cv

from .api import TpLinkAuthError, TpLinkError, TpLinkRouter
from .const import DEFAULT_TIMEOUT, DEFAULT_USERNAME, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): cv.string,
    }
)


class TpLinkLegacyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ajout d'un routeur : on vérifie l'accès avant de créer l'entrée."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            self._async_abort_entries_match({CONF_HOST: host})

            router = TpLinkRouter(
                host=host,
                password=user_input[CONF_PASSWORD],
                username=user_input.get(CONF_USERNAME, DEFAULT_USERNAME),
                timeout=DEFAULT_TIMEOUT,
            )
            try:
                info = await router.get_info()
            except TpLinkAuthError:
                errors["base"] = "invalid_auth"
            except TpLinkError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - remonté comme erreur inconnue
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.get("mac") or host)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=info.get("model") or host,
                    data=user_input,
                )
            finally:
                await router.disconnect()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
