"""Le parcours d'ajout d'un routeur, exécuté dans Home Assistant."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tplink_legacy.api import TpLinkAuthError, TpLinkError
from custom_components.tplink_legacy.const import (
    CONF_INCLUDE_SECRETS,
    DOMAIN,
    MANUAL_HOST,
)

CREDENTIALS = {CONF_PASSWORD: "secret", CONF_USERNAME: "admin"}


async def test_manual_entry_creates_config_entry(
    hass: HomeAssistant, mock_router, no_discovery
) -> None:
    """Sans routeur détecté, on tombe directement sur la saisie manuelle."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.11.1", **CREDENTIALS}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TL-WR841N (192.168.11.1)"
    assert result["data"][CONF_HOST] == "192.168.11.1"


async def test_discovery_offers_found_routers(hass: HomeAssistant, mock_router) -> None:
    """Les routeurs détectés sont proposés, puis on ne demande que les identifiants."""
    with patch(
        "custom_components.tplink_legacy.config_flow.discover",
        return_value=[{"host": "192.168.11.1", "seq": 1}, {"host": "192.168.12.1", "seq": 2}],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.12.1"}
        )

    assert result["step_id"] == "credentials"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.12.1"


async def test_discovery_can_fall_back_to_manual(hass: HomeAssistant, mock_router) -> None:
    """« Autre adresse… » renvoie vers le formulaire complet."""
    with patch(
        "custom_components.tplink_legacy.config_flow.discover",
        return_value=[{"host": "192.168.11.1", "seq": 1}],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: MANUAL_HOST}
        )

    assert result["step_id"] == "manual"


async def test_invalid_auth_is_reported(hass: HomeAssistant, mock_router, no_discovery) -> None:
    mock_router.get_info.side_effect = TpLinkAuthError("mot de passe refusé")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.11.1", **CREDENTIALS}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_unreachable_router_is_reported(
    hass: HomeAssistant, mock_router, no_discovery
) -> None:
    mock_router.get_info.side_effect = TpLinkError("injoignable")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.11.1", **CREDENTIALS}
    )

    assert result["errors"] == {"base": "cannot_connect"}


async def test_same_router_cannot_be_added_twice(
    hass: HomeAssistant, mock_router, no_discovery
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.168.11.1", **CREDENTIALS})
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.11.1", **CREDENTIALS}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(hass: HomeAssistant, mock_router) -> None:
    """Un mot de passe changé se corrige sans supprimer l'entrée."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.168.11.1", CONF_PASSWORD: "ancien", CONF_USERNAME: "admin"},
        unique_id="48:22:54:2B:A2:D0",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "nouveau"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "nouveau"


async def test_options_flow(hass: HomeAssistant, mock_router) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.168.11.1", **CREDENTIALS},
        unique_id="48:22:54:2B:A2:D0",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60, CONF_INCLUDE_SECRETS: True}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert entry.options[CONF_INCLUDE_SECRETS] is True
