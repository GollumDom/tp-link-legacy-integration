"""
Couche haut niveau : normalisation et agrégation.

Le firmware ne renvoie QUE des chaînes ; c'est ici qu'elles deviennent des
booléens, des entiers et des listes. Ces conversions sont la principale source
de bugs silencieux (un `"0"` est vrai en Python comme en JS), d'où des tests
dédiés, montés sur une session simulée plutôt que sur un vrai routeur.
"""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "tplink_legacy"))

from api.errors import TpLinkError, TpLinkUnreachableError  # noqa: E402
from api.router import TpLinkRouter  # noqa: E402


class FakeSession:
    """Session simulée : rend des réponses figées, comme le ferait le routeur."""

    def __init__(self, data: dict[str, Any], *, default: Exception | None = None) -> None:
        self.host = "192.168.0.1"
        self.data = data
        #: Erreur rendue pour tout OID absent — de quoi simuler un routeur muet
        #: aussi bien qu'un routeur qui refuse une lecture précise.
        self.default = default
        self.sets: list[tuple[str, dict, str | None]] = []
        self.logged_in = True
        self.cookie = "JSESSIONID=x"
        self.batches = 0

    def _resolve(self, oid: str):
        if oid not in self.data:
            if self.default is not None:
                raise self.default
            raise TpLinkError(f"OID absent : {oid}", host=self.host)
        value = self.data[oid]
        if isinstance(value, Exception):
            raise value
        return value

    async def get(self, oid, **_):
        value = self._resolve(oid)
        return value[0] if isinstance(value, list) else value

    async def get_list(self, oid, **_):
        value = self._resolve(oid)
        return value if isinstance(value, list) else [value]

    async def set(self, oid, attrs, *, stack=None, p_stack=None):
        self.sets.append((oid, dict(attrs), stack))
        return True

    async def execute(self, actions):
        """Le lot unique utilisé par `get_status`.

        Reproduit le comportement du routeur : une seule action refusée fait
        échouer la requête entière, ce qui doit déclencher le repli section par
        section.
        """
        self.batches += 1
        results = []
        for action in actions:
            value = self._resolve(action["oid"])
            results.append(value if isinstance(value, list) else [value])
        return SimpleNamespace(ret=0, results=results, script="")


def build_router(data: dict[str, Any], *, default: Exception | None = None) -> TpLinkRouter:
    router = TpLinkRouter(host="192.168.0.1", password="x")
    router.session = FakeSession(data, default=default)  # type: ignore[assignment]
    return router


class TestNormalisation(unittest.IsolatedAsyncioTestCase):

    async def test_info(self):
        router = build_router(
            {
                "IGD_DEV_INFO": {
                    "modelName": "TL-WR841N",
                    "description": "  Wireless N Router  ",
                    "softwareVersion": "0.9.1 4.17",
                    "hardwareVersion": "WR841N v14",
                    "upTime": "123456",
                },
                "SYS_CFG": {"flashMac": "AA:BB:CC:DD:EE:FF"},
                "MULTIMODE": {"mode": "router"},
            }
        )
        info = await router.get_info()

        self.assertEqual(info["model"], "TL-WR841N")
        self.assertEqual(info["description"], "Wireless N Router", "espaces retirés")
        self.assertEqual(info["uptime"], 123456, "converti en entier")
        self.assertEqual(info["mac"], "AA:BB:CC:DD:EE:FF")

    async def test_info_survit_aux_oid_absents(self):
        """`SYS_CFG` et `MULTIMODE` n'existent pas sur tous les firmwares."""
        router = build_router({"IGD_DEV_INFO": {"modelName": "TL-WR841N", "upTime": "1"}})
        info = await router.get_info()

        self.assertEqual(info["model"], "TL-WR841N")
        self.assertIsNone(info["mac"])
        self.assertIsNone(info["mode"])

    async def test_lan_booleen_dhcp(self):
        router = build_router(
            {
                "LAN_IP_INTF": [
                    {
                        "IPInterfaceIPAddress": "192.168.0.1",
                        "IPInterfaceSubnetMask": "255.255.255.0",
                        "X_TP_MACAddress": "AA:BB:CC:DD:EE:FF",
                    }
                ],
                "LAN_HOST_CFG": [{"DHCPServerEnable": "0"}],
            }
        )
        lan = await router.get_lan()

        self.assertEqual(lan["ip"], "192.168.0.1")
        # Le piège : "0" est une chaîne non vide, donc vraie si on ne convertit pas.
        self.assertIs(lan["dhcpEnabled"], False)

    async def test_wan_choisit_le_profil_connecte(self):
        router = build_router(
            {
                "WAN_IP_CONN": [
                    {"enable": "1", "connectionStatus": "Disconnected", "name": "statique"},
                    {
                        "enable": "1",
                        "connectionStatus": "Connected",
                        "name": "dhcp",
                        "externalIPAddress": "88.1.2.3",
                        "DNSServers": "8.8.8.8, 0.0.0.0 ,1.1.1.1",
                        "uptime": "42",
                        "MACAddress": "",
                    },
                ],
                "WAN_PPP_CONN": [{"enable": "0", "connectionStatus": "Connected", "name": "pppoe"}],
                "WAN_COMMON_INTF_CFG": [{"WANAccessType": "Ethernet"}],
                "WAN_ETH_INTF": [{"status": "Up", "maxBitRate": "100", "duplexMode": "Full"}],
            }
        )
        wan = await router.get_wan()

        self.assertTrue(wan["connected"])
        self.assertEqual(wan["profile"], "dhcp", "le profil connecté prime")
        self.assertEqual(wan["protocol"], "IPoE")
        self.assertEqual(wan["dns"], ["8.8.8.8", "1.1.1.1"], "0.0.0.0 filtré, espaces retirés")
        self.assertIsNone(wan["mac"], "chaîne vide ramenée à None")
        self.assertEqual(wan["uptime"], 42)
        self.assertEqual(wan["link"], {"up": True, "speed": "100", "duplex": "Full"})

    async def test_wan_ignore_les_profils_desactives(self):
        router = build_router(
            {
                "WAN_IP_CONN": [{"enable": "0", "connectionStatus": "Connected", "name": "off"}],
                "WAN_PPP_CONN": [],
                "WAN_COMMON_INTF_CFG": [],
                "WAN_ETH_INTF": [],
            }
        )
        wan = await router.get_wan()

        self.assertFalse(wan["connected"])
        self.assertIsNone(wan["profile"])

    async def test_wireless_masque_la_cle_par_defaut(self):
        data = {
            "LAN_WLAN": [
                {
                    "__stack": "1,0,0,0,0,0",
                    "enable": "1",
                    "SSID": "Maison",
                    "X_TP_Band": "2.4GHz",
                    "SSIDAdvertisementEnabled": "0",
                    "channel": "6",
                    "beaconType": "11i",
                    "IEEE11iEncryptionModes": "AESEncryption",
                    "IEEE11iAuthenticationMode": "PSKAuthentication",
                    "X_TP_PreSharedKey": "secret",
                }
            ]
        }

        radios = await build_router(data).get_wireless()
        self.assertNotIn("passphrase", radios[0], "la clé WPA ne fuit pas par défaut")
        self.assertTrue(radios[0]["enabled"])
        self.assertTrue(radios[0]["hidden"], "SSIDAdvertisementEnabled=0 → SSID masqué")
        self.assertEqual(radios[0]["channel"], 6)
        self.assertEqual(radios[0]["security"]["mode"], "WPA2-PSK")
        self.assertFalse(radios[0]["security"]["enterprise"])

        radios = await build_router(data).get_wireless(include_secrets=True)
        self.assertEqual(radios[0]["passphrase"], "secret")

    async def test_securite_wep_et_ouverte(self):
        wep = await build_router(
            {"LAN_WLAN": [{"basicEncryptionModes": "WEPEncryption"}]}
        ).get_wireless()
        self.assertEqual(wep[0]["security"]["mode"], "WEP")

        ouvert = await build_router(
            {"LAN_WLAN": [{"basicEncryptionModes": "None"}]}
        ).get_wireless()
        self.assertEqual(ouvert[0]["security"]["mode"], "None")


class TestClients(unittest.IsolatedAsyncioTestCase):

    DATA = {
        "LAN_HOST_ENTRY": [
            {
                "IPAddress": "192.168.0.10",
                "MACAddress": "aa-bb-cc-dd-ee-01",
                "hostName": "portable",
                "leaseTimeRemaining": "7200",
                "X_TP_ConnType": "1",
            },
            {
                "IPAddress": "192.168.0.9",
                "MACAddress": "AA:BB:CC:DD:EE:02",
                "hostName": "Unknown",
                "leaseTimeRemaining": "3600",
                "X_TP_ConnType": "0",
            },
        ],
        "LAN_WLAN_ASSOC_DEV": [
            {
                "associatedDeviceMACAddress": "AA:BB:CC:DD:EE:01",
                "X_TP_HostName": "wlan0",
                "X_TP_TotalPacketsSent": "10",
                "X_TP_TotalPacketsReceived": "20",
            },
            {
                "associatedDeviceMACAddress": "AA:BB:CC:DD:EE:03",
                "X_TP_HostName": "wlan0",
                "X_TP_TotalPacketsSent": "1",
                "X_TP_TotalPacketsReceived": "2",
            },
        ],
    }

    async def test_fusion_par_mac(self):
        clients = await build_router(self.DATA).get_clients()

        self.assertEqual(len(clients), 3, "3 MAC distinctes, pas de doublon")
        par_mac = {c["mac"]: c for c in clients}

        # Le bail DHCP et la station Wi-Fi portent la même MAC, écrite
        # différemment (tirets vs deux-points) : la normalisation doit les réunir.
        fusionne = par_mac["AA:BB:CC:DD:EE:01"]
        self.assertEqual(fusionne["ip"], "192.168.0.10")
        self.assertEqual(fusionne["hostname"], "portable")
        self.assertEqual(fusionne["connection"], "wireless")
        self.assertEqual(fusionne["packetsSent"], 10)

        # Station Wi-Fi sans bail DHCP : présente, mais sans IP.
        self.assertIsNone(par_mac["AA:BB:CC:DD:EE:03"]["ip"])

        # Bail seul, filaire, hostname "Unknown" ramené à None.
        cable = par_mac["AA:BB:CC:DD:EE:02"]
        self.assertEqual(cable["connection"], "wired")
        self.assertIsNone(cable["hostname"])

    async def test_tri_numerique_par_ip(self):
        """`192.168.0.9` avant `192.168.0.10` — un tri lexical les inverserait."""
        clients = await build_router(self.DATA).get_clients()
        avec_ip = [c["ip"] for c in clients if c["ip"]]
        self.assertEqual(avec_ip, ["192.168.0.9", "192.168.0.10"])


class TestOperations(unittest.IsolatedAsyncioTestCase):

    async def test_set_wireless_enabled_cible_la_bonne_radio(self):
        router = build_router(
            {
                "LAN_WLAN": [
                    {"__stack": "1,0,0,0,0,0", "X_TP_Band": "2.4GHz", "name": "wlan0"},
                    {"__stack": "2,0,0,0,0,0", "X_TP_Band": "5GHz", "name": "wlan1"},
                ]
            }
        )

        await router.set_wireless_enabled(False, band="5GHz")
        oid, attrs, stack = router.session.sets[-1]  # type: ignore[attr-defined]
        self.assertEqual(oid, "LAN_WLAN")
        self.assertEqual(attrs, {"enable": 0})
        self.assertEqual(stack, "2,0,0,0,0,0", "la stack de la radio 5 GHz")

    async def test_set_wireless_enabled_par_defaut_premiere_radio(self):
        router = build_router({"LAN_WLAN": [{"__stack": "1,0,0,0,0,0", "X_TP_Band": "2.4GHz"}]})
        await router.set_wireless_enabled(True)
        self.assertEqual(router.session.sets[-1][2], "1,0,0,0,0,0")  # type: ignore[attr-defined]

    async def test_bande_inconnue(self):
        router = build_router({"LAN_WLAN": [{"__stack": "1,0,0,0,0,0", "X_TP_Band": "2.4GHz"}]})
        with self.assertRaises(TpLinkError):
            await router.set_wireless_enabled(True, band="6GHz")

    async def test_ssid_valide(self):
        router = build_router({"LAN_WLAN": [{"__stack": "1,0,0,0,0,0"}]})
        with self.assertRaises(TpLinkError):
            await router.set_ssid("")
        with self.assertRaises(TpLinkError):
            await router.set_ssid("x" * 33)

        await router.set_ssid("Maison")
        self.assertEqual(router.session.sets[-1][1], {"SSID": "Maison"})  # type: ignore[attr-defined]


class TestStatus(unittest.IsolatedAsyncioTestCase):

    async def test_une_section_en_echec_ne_casse_pas_le_reste(self):
        """C'est la propriété qui compte pour le coordinator Home Assistant."""
        router = build_router(
            {
                "IGD_DEV_INFO": {"modelName": "TL-WR841N", "upTime": "1"},
                "LAN_IP_INTF": [{"IPInterfaceIPAddress": "192.168.0.1"}],
                "LAN_HOST_CFG": [{"DHCPServerEnable": "1"}],
                # WAN et Wi-Fi absents → sections en erreur
                "LAN_HOST_ENTRY": [],
                "LAN_WLAN_ASSOC_DEV": [],
            }
        )
        status = await router.get_status()

        self.assertEqual(status["info"]["model"], "TL-WR841N")
        self.assertEqual(status["lan"]["ip"], "192.168.0.1")
        self.assertIsNone(status["wireless"], "section indisponible")
        self.assertIn("wireless", status["errors"])
        self.assertEqual(status["clientCount"], 0)

    async def test_clientcount(self):
        router = build_router(
            {
                "IGD_DEV_INFO": {"modelName": "X", "upTime": "1"},
                "LAN_IP_INTF": [{}],
                "LAN_HOST_CFG": [],
                "WAN_IP_CONN": [],
                "WAN_PPP_CONN": [],
                "WAN_COMMON_INTF_CFG": [],
                "WAN_ETH_INTF": [],
                "LAN_WLAN": [],
                "LAN_HOST_ENTRY": [
                    {"IPAddress": "192.168.0.2", "MACAddress": "AA:BB:CC:DD:EE:01"},
                ],
                "LAN_WLAN_ASSOC_DEV": [],
            }
        )
        status = await router.get_status()

        self.assertEqual(status["clientCount"], 1)
        self.assertNotIn("errors", status, "aucune section en échec")


class TestRouteurQuiNeRepondPlus(unittest.IsolatedAsyncioTestCase):
    """Un routeur muet ne doit être ni relancé, ni maquillé en relevé partiel.

    Le httpd de ces firmwares ne tient qu'une poignée de sockets : le repli
    section par section, c'est douze lectures — et jusqu'à douze ouvertures de
    session — pour douze fois rien. C'est ainsi qu'un routeur qui répondait mal
    finit par ne plus répondre du tout.
    """

    #: Lectures menées par le repli section par section.
    SECTIONS = 5

    async def test_routeur_muet_abandonne_des_le_lot(self):
        router = build_router({}, default=TpLinkUnreachableError("injoignable"))

        with self.assertRaises(TpLinkUnreachableError):
            await router.get_status()

        self.assertEqual(router.session.batches, 1, "un seul essai, puis on renonce")

    async def test_routeur_muet_en_cours_de_repli(self):
        """Le lot échoue pour une autre raison, puis le routeur se tait."""
        router = build_router(
            {"IGD_DEV_INFO": TpLinkError("CMM_INVALID_ARGUMENTS", code=9003)},
            default=TpLinkUnreachableError("injoignable"),
        )

        with self.assertRaises(TpLinkUnreachableError):
            await router.get_status()

    async def test_aucune_section_livree_est_un_echec(self):
        """Rien de lisible : c'est un relevé raté, pas un relevé partiel."""
        router = build_router({})

        with self.assertRaises(TpLinkError) as caught:
            await router.get_status()

        self.assertNotIsInstance(caught.exception, TpLinkUnreachableError)
        self.assertIn("aucune section", str(caught.exception))

    async def test_wan_entierement_refuse_est_une_section_en_erreur(self):
        """Un WAN vide se lirait « pas d'Internet » : il faut dire « refusé »."""
        router = build_router(
            {
                "IGD_DEV_INFO": {"modelName": "X", "upTime": "1"},
                "LAN_IP_INTF": [{}],
                "LAN_HOST_CFG": [],
                "LAN_WLAN": [],
                "LAN_HOST_ENTRY": [],
                "LAN_WLAN_ASSOC_DEV": [],
            }
        )

        status = await router.get_status()

        self.assertIsNone(status["wan"])
        self.assertIn("wan", status["errors"])

    async def test_clients_entierement_refuses_est_une_section_en_erreur(self):
        """Sinon tous les appareils suivis passeraient « absents » d'un coup."""
        router = build_router(
            {
                "IGD_DEV_INFO": {"modelName": "X", "upTime": "1"},
                "LAN_IP_INTF": [{}],
                "LAN_HOST_CFG": [],
                "WAN_IP_CONN": [],
                "WAN_PPP_CONN": [],
                "WAN_COMMON_INTF_CFG": [],
                "WAN_ETH_INTF": [],
                "LAN_WLAN": [],
            }
        )

        status = await router.get_status()

        self.assertIsNone(status["clients"])
        self.assertIn("clients", status["errors"])
        self.assertIsNone(status["clientCount"])


if __name__ == "__main__":
    unittest.main()


class TestStatusEnUnLot(unittest.IsolatedAsyncioTestCase):
    """`get_status` doit tenir en une seule requête, et savoir se replier."""

    DATA = {
        "IGD_DEV_INFO": {"modelName": "TL-WR841N", "upTime": "120"},
        "SYS_CFG": {"flashMac": "48:22:54:2B:A2:D0"},
        "MULTIMODE": {"mode": "Router"},
        "LAN_IP_INTF": [{"IPInterfaceIPAddress": "192.168.11.1"}],
        "LAN_HOST_CFG": [{"DHCPServerEnable": "1"}],
        "WAN_IP_CONN": [{"enable": "1", "connectionStatus": "Connected",
                         "externalIPAddress": "88.1.2.3"}],
        "WAN_PPP_CONN": [],
        "WAN_COMMON_INTF_CFG": [{"WANAccessType": "Ethernet"}],
        "WAN_ETH_INTF": [{"status": "Up"}],
        "LAN_WLAN": [{"__stack": "1,1,0,0,0,0", "SSID": "MAISONDOMO_1",
                      "enable": "1", "channel": "13", "X_TP_Band": "2.4GHz"}],
        "LAN_HOST_ENTRY": [{"IPAddress": "192.168.11.9",
                            "MACAddress": "44:17:93:A4:D3:EC",
                            "X_TP_ConnType": "1"}],
        "LAN_WLAN_ASSOC_DEV": [{"associatedDeviceMACAddress": "44:17:93:A4:D3:EC"}],
    }

    async def test_une_seule_requete(self):
        router = build_router(dict(self.DATA))
        status = await router.get_status()

        self.assertEqual(router.session.batches, 1, "tout doit tenir en un lot")
        self.assertEqual(status["info"]["model"], "TL-WR841N")
        self.assertEqual(status["lan"]["ip"], "192.168.11.1")
        self.assertTrue(status["wan"]["connected"])
        self.assertEqual(status["wireless"][0]["ssid"], "MAISONDOMO_1")
        self.assertEqual(status["clientCount"], 1)
        self.assertNotIn("errors", status)

    async def test_repli_section_par_section_si_le_lot_echoue(self):
        """Un OID refusé fait échouer le lot entier : on relit section par section."""
        data = dict(self.DATA)
        data["LAN_WLAN"] = TpLinkError("CMM_INVALID_ARGUMENTS", code=9003)

        router = build_router(data)
        status = await router.get_status()

        self.assertEqual(router.session.batches, 1, "le lot n'est tenté qu'une fois")
        # les sections lisibles sont bien là, seule la radio manque
        self.assertEqual(status["info"]["model"], "TL-WR841N")
        self.assertEqual(status["lan"]["ip"], "192.168.11.1")
        self.assertIsNone(status["wireless"])
        self.assertIn("wireless", status["errors"])

    async def test_le_masque_ppp_n_est_pas_demande(self):
        """`subnetMask` sur WAN_PPP_CONN fait échouer toute la requête."""
        from custom_components.tplink_legacy.api.router import ATTRS_WAN_PPP

        self.assertNotIn("subnetMask", ATTRS_WAN_PPP)
        self.assertIn("remoteIPAddress", ATTRS_WAN_PPP)


class TestRadioFantome(unittest.IsolatedAsyncioTestCase):
    """Une radio déclarée sans matériel derrière n'annonce aucun débit."""

    async def test_presence_deduite_des_debits(self):
        router = build_router({
            "LAN_WLAN": [
                {"__stack": "1,1,0,0,0,0", "SSID": "reelle", "X_TP_Band": "2.4GHz",
                 "possibleDataTransmitRates": "5.5,12,18,24"},
                {"__stack": "1,2,0,0,0,0", "SSID": "fantome", "X_TP_Band": "5GHz",
                 "possibleDataTransmitRates": ""},
            ]
        })
        radios = await router.get_wireless()
        self.assertTrue(radios[0]["present"])
        self.assertFalse(radios[1]["present"])
