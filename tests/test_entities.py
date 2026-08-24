"""Chargement de l'intégration et comportement des entités, dans Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tplink_legacy.const import DOMAIN

from .sample_data import STATUS

DATA = {CONF_HOST: "192.168.11.1", CONF_PASSWORD: "secret", CONF_USERNAME: "admin"}


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=DATA, unique_id="48:22:54:2B:A2:D0", title="TL-WR841N"
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entry_loads(hass: HomeAssistant, mock_router) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED


async def test_device_carries_router_identity(hass: HomeAssistant, mock_router) -> None:
    entry = await _setup(hass)
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    assert device is not None
    assert device.model == "TL-WR841N"
    assert device.sw_version == STATUS["info"]["firmware"]
    assert device.configuration_url == "http://192.168.11.1/"


async def test_sensors(hass: HomeAssistant, mock_router) -> None:
    await _setup(hass)

    assert hass.states.get("sensor.tl_wr841n_connected_devices").state == "2"
    assert hass.states.get("sensor.tl_wr841n_public_ip_address").state == "88.120.10.5"
    assert hass.states.get("sensor.tl_wr841n_local_ip_address").state == "192.168.11.1"
    assert hass.states.get("sensor.tl_wr841n_wan_status").state == "Connected"
    # l'uptime devient un horodatage
    assert hass.states.get("sensor.tl_wr841n_up_since").state not in (None, "unknown")


async def test_internet_binary_sensor(hass: HomeAssistant, mock_router) -> None:
    await _setup(hass)
    assert hass.states.get("binary_sensor.tl_wr841n_internet").state == STATE_ON


async def test_one_switch_per_radio_with_attributes(
    hass: HomeAssistant, mock_router
) -> None:
    await _setup(hass)

    radio_24 = hass.states.get("switch.tl_wr841n_wi_fi_2_4ghz")
    radio_5 = hass.states.get("switch.tl_wr841n_wi_fi_5ghz")

    assert radio_24.state == STATE_ON
    # la 5 GHz du jeu d'essai est déclarée par le firmware sans matériel
    # derrière : l'entité existe mais reste grisée
    assert radio_5.state == "unavailable"
    assert radio_24.attributes["ssid"] == "MAISONDOMO_1"
    assert radio_24.attributes["channel"] == 13
    assert radio_24.attributes["security"] == "WPA2-PSK"


async def test_switch_turns_radio_off(hass: HomeAssistant, mock_router) -> None:
    await _setup(hass)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.tl_wr841n_wi_fi_2_4ghz"},
        blocking=True,
    )
    await hass.async_block_till_done()

    mock_router.set_wireless_enabled.assert_awaited_once_with(False, band="2.4GHz")


async def test_reboot_button(hass: HomeAssistant, mock_router) -> None:
    await _setup(hass)

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.tl_wr841n_reboot"},
        blocking=True,
    )
    await hass.async_block_till_done()

    mock_router.reboot.assert_awaited_once()


async def test_device_trackers_are_registered(hass: HomeAssistant, mock_router) -> None:
    """Un tracker est créé par client, identifié par son adresse MAC.

    Contrairement au défaut de `ScannerEntity`, elles sont actives dès leur
    création : sans cela il n'y a aucun suivi de présence tant que l'utilisateur
    n'a pas activé chaque entité à la main.
    """
    entry = await _setup(hass)
    registry = er.async_get(hass)

    entries = [
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "device_tracker"
    ]
    assert {item.unique_id for item in entries} == {
        "44:17:93:A4:D3:EC",
        "20:6E:F1:03:B0:70",
    }
    # activées d'emblée : sur un routeur domestique, le suivi de présence est
    # la raison principale d'installer l'intégration
    assert all(item.disabled_by is None for item in entries)
    assert hass.states.get("device_tracker.salon_tv").state == STATE_HOME


async def test_tracker_is_active_for_a_known_device(
    hass: HomeAssistant, mock_router
) -> None:
    """Si Home Assistant connaît déjà l'appareil, son tracker est actif."""
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "44:17:93:a4:d3:ec")},
        name="Salon TV",
    )

    await _setup(hass)

    tracker = "device_tracker.salon_tv"
    assert hass.states.get(tracker).state == STATE_HOME
    assert hass.states.get(tracker).attributes["ip"] == "192.168.11.9"
    assert hass.states.get(tracker).attributes["connection"] == "wireless"


async def test_tracker_goes_away_when_client_disappears(
    hass: HomeAssistant, mock_router
) -> None:
    """Un client connu qui disparaît devient absent, il n'est pas supprimé."""
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "44:17:93:a4:d3:ec")},
        name="Salon TV",
    )

    entry = await _setup(hass)
    tracker = "device_tracker.salon_tv"
    assert hass.states.get(tracker).state == STATE_HOME

    # le routeur ne voit plus que le second client
    mock_router.get_status.return_value = {
        **STATUS,
        "clients": STATUS["clients"][1:],
        "clientCount": 1,
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(tracker).state == STATE_NOT_HOME


async def test_degraded_router_does_not_break_setup(
    hass: HomeAssistant, mock_router
) -> None:
    """Hors LAN, le firmware refuse les données personnelles : le reste doit tenir."""
    mock_router.get_status.return_value = {
        "host": "192.168.11.1",
        "name": "192.168.11.1",
        "info": STATUS["info"],
        "lan": None,
        "wan": None,
        "wireless": None,
        "clients": [],
        "clientCount": 0,
        "errors": {"lan": {"message": "HTTP 500"}, "wireless": {"message": "HTTP 500"}},
    }

    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    # les capteurs existent, sans valeur, et aucun interrupteur n'est créé
    assert hass.states.get("sensor.tl_wr841n_connected_devices").state == "0"
    assert hass.states.get("switch.tl_wr841n_wi_fi_2_4ghz") is None


async def test_unload(hass: HomeAssistant, mock_router) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_router.disconnect.assert_awaited()


async def test_polling_switch_suspends_updates(hass: HomeAssistant, mock_router) -> None:
    """Couper l'interrogation libère le routeur et arrête la minuterie.

    Ces firmwares n'acceptent qu'un administrateur : tant que Home Assistant
    interroge, l'interface web se fait déconnecter, et réciproquement.
    """
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    switch = "switch.tl_wr841n_router_polling"

    assert hass.states.get(switch).state == STATE_ON
    assert coordinator.update_interval is not None

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: switch}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(switch).state == STATE_OFF
    assert coordinator.polling is False
    # plus aucune interrogation programmée, et la session est rendue au routeur
    assert coordinator.update_interval is None
    mock_router.disconnect.assert_awaited()

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(switch).state == STATE_ON
    assert coordinator.polling is True
    assert coordinator.update_interval is not None


async def test_polling_switch_stays_available_when_router_is_down(
    hass: HomeAssistant, mock_router
) -> None:
    """L'interrupteur doit rester manipulable même routeur injoignable."""
    from custom_components.tplink_legacy.api import TpLinkError

    entry = await _setup(hass)
    mock_router.get_status.side_effect = TpLinkError("injoignable")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("switch.tl_wr841n_router_polling")
    assert state.state == STATE_ON
    # les autres entités passent indisponibles, pas celle-ci
    assert hass.states.get("sensor.tl_wr841n_connected_devices").state == "unavailable"


async def test_last_known_values_survive_a_refused_section(
    hass: HomeAssistant, mock_router
) -> None:
    """Une section refusée ne doit pas effacer ce qui avait été lu.

    Ce firmware répond de façon intermittente : sans cela les entités
    clignotent entre leur valeur et « inconnu ».
    """
    entry = await _setup(hass)
    assert hass.states.get("sensor.tl_wr841n_public_ip_address").state == "88.120.10.5"
    assert hass.states.get("switch.tl_wr841n_wi_fi_2_4ghz").attributes["ssid"] == "MAISONDOMO_1"

    # le routeur ne renvoie plus que les informations générales
    mock_router.get_status.return_value = {
        "host": "192.168.11.1",
        "name": "192.168.11.1",
        "info": STATUS["info"],
        "lan": None,
        "wan": None,
        "wireless": None,
        "clients": [],
        "clientCount": 0,
        "errors": {"lan": {"message": "HTTP 500"}, "wireless": {"message": "HTTP 500"}},
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # les valeurs précédentes sont conservées, et signalées comme non rafraîchies
    assert hass.states.get("sensor.tl_wr841n_public_ip_address").state == "88.120.10.5"
    assert hass.states.get("switch.tl_wr841n_wi_fi_2_4ghz").attributes["ssid"] == "MAISONDOMO_1"
    assert set(entry.runtime_data.data["stale"]) == {"lan", "wan", "wireless"}


async def test_repair_issue_when_router_refuses_sections(
    hass: HomeAssistant, mock_router
) -> None:
    """Le refus doit remonter dans « Réparations », pas seulement dans les journaux."""
    from homeassistant.helpers import issue_registry as ir

    entry = await _setup(hass)
    registry = ir.async_get(hass)
    issue_id = f"restricted_{entry.entry_id}"

    # routeur complet : aucun signalement
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    mock_router.get_status.return_value = {
        "host": "192.168.11.1",
        "name": "192.168.11.1",
        "info": STATUS["info"],
        "lan": None,
        "wan": None,
        "wireless": None,
        "clients": [],
        "clientCount": 0,
        "errors": {"lan": {"message": "HTTP 500"}, "wireless": {"message": "HTTP 500"}},
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["sections"] == "lan, wireless"
    assert issue.translation_placeholders["host"] == "192.168.11.1"

    # le routeur redevient complet : le signalement disparaît
    mock_router.get_status.return_value = STATUS
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_capteur_etat_des_donnees(hass: HomeAssistant, mock_router) -> None:
    """Un état lisible en un coup d'œil, y compris routeur injoignable."""
    from custom_components.tplink_legacy.api import TpLinkError

    entry = await _setup(hass)
    etat = "sensor.tl_wr841n_data_status"

    assert hass.states.get(etat).state == "complet"

    # le routeur ne livre plus qu'une partie
    mock_router.get_status.return_value = {
        **STATUS, "lan": None, "wireless": None,
        "errors": {"lan": {"message": "HTTP 500"}, "wireless": {"message": "HTTP 500"}},
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(etat)
    assert state.state == "partiel"
    assert state.attributes["sections_refusees"] == ["lan", "wireless"]

    # routeur totalement injoignable : le capteur reste lisible
    mock_router.get_status.side_effect = TpLinkError("injoignable")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(etat)
    assert state.state == "injoignable"
    assert state.attributes["derniere_erreur"] is not None
    # les autres capteurs passent indisponibles, celui-ci non
    assert hass.states.get("sensor.tl_wr841n_connected_devices").state == "unavailable"


async def test_radio_absente_du_materiel_est_grisee(
    hass: HomeAssistant, mock_router
) -> None:
    """Le firmware déclare une radio 5 GHz même sur les modèles mono-bande.

    L'entité reste visible — pour que l'absence soit explicite — mais grisée.
    """
    await _setup(hass)

    presente = hass.states.get("switch.tl_wr841n_wi_fi_2_4ghz")
    fantome = hass.states.get("switch.tl_wr841n_wi_fi_5ghz")

    assert presente.state == STATE_ON
    assert presente.attributes["materiel_present"] is True

    # créée et visible, mais non manipulable
    assert fantome is not None
    assert fantome.state == "unavailable"


async def test_up_since_ne_derive_pas_quand_info_est_conservee(
    hass: HomeAssistant, mock_router, freezer
) -> None:
    """Le firmware donne une durée, pas une date.

    Recalculer « maintenant moins la durée » sur une durée conservée du relevé
    précédent ferait avancer l'instant de démarrage au rythme de l'horloge : le
    routeur paraîtrait redémarrer à chaque relevé.
    """
    entry = await _setup(hass)
    up_since = hass.states.get("sensor.tl_wr841n_up_since").state
    assert up_since not in (None, "unknown")

    # dix minutes plus tard, le routeur refuse la section « info »
    freezer.tick(600)
    mock_router.get_status.return_value = {
        "host": "192.168.11.1",
        "name": "192.168.11.1",
        "info": None,
        "lan": STATUS["lan"],
        "wan": STATUS["wan"],
        "wireless": STATUS["wireless"],
        "clients": STATUS["clients"],
        "clientCount": STATUS["clientCount"],
        "errors": {"info": {"message": "HTTP 500"}},
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.tl_wr841n_up_since").state == up_since


async def test_polling_recule_quand_le_routeur_ne_repond_plus(
    hass: HomeAssistant, mock_router
) -> None:
    """Insister toutes les trente secondes achève le httpd au lieu de le réveiller."""
    from custom_components.tplink_legacy.api import TpLinkError

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    normal = coordinator.update_interval

    mock_router.get_status.side_effect = TpLinkError("injoignable")
    await coordinator.async_refresh()
    first_backoff = coordinator.update_interval
    assert first_backoff > normal

    await coordinator.async_refresh()
    assert coordinator.update_interval > first_backoff

    # le routeur revient : on reprend le rythme normal
    mock_router.get_status.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.update_interval == normal


async def test_le_recul_ne_relance_pas_une_interrogation_suspendue(
    hass: HomeAssistant, mock_router
) -> None:
    from custom_components.tplink_legacy.api import TpLinkError

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.set_polling(False)

    mock_router.get_status.side_effect = TpLinkError("injoignable")
    await coordinator.async_refresh()

    assert coordinator.update_interval is None
