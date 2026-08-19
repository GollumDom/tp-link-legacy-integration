"""
API haut niveau d'un routeur TP-Link — portage de ``src/api/router.js``.

Les valeurs renvoyées par le firmware sont toutes des chaînes ; cette couche les
normalise (booléens, nombres, listes) et regroupe les OID en objets directement
exploitables, notamment par une intégration Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Final, Mapping, Sequence

from .errors import TpLinkError
from .oids import OID
from .session import ACT, OP, Action, TpLinkSession, is_disconnect_error

__all__ = ["TpLinkRouter"]


def _bool(value: str | None) -> bool:
    return value in ("1", "true", "Enabled")


def _int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _list(value: str | None) -> list[str]:
    return [
        part
        for part in (p.strip() for p in (value or "").split(","))
        if part and part not in ("0.0.0.0", "::")
    ]


def _normalize_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    return mac.upper().replace("-", ":")


def _ip_sort_key(ip: str | None) -> tuple:
    """Tri numérique par adresse : ``192.168.0.9`` avant ``192.168.0.10``.

    Le JS s'appuyait sur ``localeCompare(..., {numeric: true})`` ; en Python on
    décompose explicitement, ce qui trie correctement même sur des IPv6 ou des
    valeurs absentes (rejetées en fin de liste).
    """
    if not ip:
        return (1,)
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return (0, tuple(int(p) for p in parts))
    return (0, ip)


async def _safe(coro, default):
    """Exécute ``coro`` et rend ``default`` en cas d'échec.

    Équivalent des ``.catch(() => …)`` du JS : sur ce firmware, plusieurs OID
    n'existent que sur certains modèles, et leur absence ne doit pas faire
    tomber la lecture complète.
    """
    try:
        return await coro
    except Exception:  # noqa: BLE001
        return default


_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------- Attributs --
#
# Listes figées : elles servent aussi bien aux lectures individuelles qu'au lot
# unique de :meth:`TpLinkRouter.get_status`.

ATTRS_INFO: Final = [
    "modelName",
    "description",
    "softwareVersion",
    "hardwareVersion",
    "upTime",
]
ATTRS_LAN_INTF: Final = [
    "IPInterfaceIPAddress",
    "IPInterfaceSubnetMask",
    "X_TP_MACAddress",
]
ATTRS_WAN_IP: Final = [
    "enable",
    "connectionStatus",
    "externalIPAddress",
    "subnetMask",
    "defaultGateway",
    "DNSServers",
    "MACAddress",
    "uptime",
    "name",
]
#: Une liaison PPP n'a pas de masque de sous-réseau : demander ``subnetMask``
#: fait échouer la requête entière avec ``CMM_INVALID_ARGUMENTS``.
ATTRS_WAN_PPP: Final = [
    "enable",
    "connectionStatus",
    "externalIPAddress",
    "remoteIPAddress",
    "defaultGateway",
    "DNSServers",
    "MACAddress",
    "uptime",
    "name",
    "transportType",
]
ATTRS_ETH: Final = ["status", "maxBitRate", "duplexMode"]
ATTRS_HOSTS: Final = [
    "IPAddress",
    "MACAddress",
    "hostName",
    "leaseTimeRemaining",
    "X_TP_ConnType",
]
ATTRS_ASSOC: Final = [
    "associatedDeviceMACAddress",
    "X_TP_TotalPacketsSent",
    "X_TP_TotalPacketsReceived",
    "X_TP_HostName",
]


# ------------------------------------------------------------ Mise en forme --
#
# Séparées des lectures : les mêmes fonctions servent aux appels unitaires et au
# lot unique, ce qui évite que les deux chemins divergent.


def _build_info(
    host: str,
    info: Mapping[str, str] | None,
    sys_cfg: Mapping[str, str] | None,
    mode: Mapping[str, str] | None,
) -> dict[str, Any]:
    info = info or {}
    return {
        "host": host,
        "model": info.get("modelName"),
        "description": (info.get("description") or "").strip() or None,
        "firmware": info.get("softwareVersion"),
        "hardware": info.get("hardwareVersion"),
        "uptime": _int(info.get("upTime")),
        "mac": (sys_cfg or {}).get("flashMac"),
        "mode": (mode or {}).get("mode"),
    }


def _build_lan(
    intf: Sequence[Mapping[str, str]], dhcp: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    first = intf[0] if intf else {}
    return {
        "ip": first.get("IPInterfaceIPAddress"),
        "netmask": first.get("IPInterfaceSubnetMask"),
        "mac": first.get("X_TP_MACAddress"),
        "dhcpEnabled": _bool(dhcp[0].get("DHCPServerEnable")) if dhcp else None,
    }


def _build_wan(
    ip_conns: Sequence[Mapping[str, str]],
    ppp_conns: Sequence[Mapping[str, str]],
    common: Sequence[Mapping[str, str]],
    eth: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    candidates = [
        {**conn, "protocol": protocol}
        for conns, protocol in ((ip_conns, "IPoE"), (ppp_conns, "PPPoE"))
        for conn in conns
        if _bool(conn.get("enable"))
    ]
    active = next(
        (c for c in candidates if c.get("connectionStatus") == "Connected"),
        candidates[0] if candidates else None,
    ) or {}
    link_up = next((e for e in eth if e.get("status") == "Up"), eth[0] if eth else None)

    return {
        "connected": active.get("connectionStatus") == "Connected",
        "status": active.get("connectionStatus"),
        "protocol": active.get("protocol"),
        "profile": active.get("name"),
        "ip": active.get("externalIPAddress"),
        # Une liaison PPP expose l'adresse du pair au lieu d'un masque.
        "netmask": active.get("subnetMask"),
        "peer": active.get("remoteIPAddress"),
        "gateway": active.get("defaultGateway"),
        "dns": _list(active.get("DNSServers")),
        "mac": active.get("MACAddress") or None,
        "uptime": _int(active.get("uptime")),
        "accessType": common[0].get("WANAccessType") if common else None,
        "link": {
            "up": link_up.get("status") == "Up",
            "speed": link_up.get("maxBitRate"),
            "duplex": link_up.get("duplexMode"),
        }
        if link_up
        else None,
    }


def _build_wireless(
    radios: Sequence[Mapping[str, str]], *, include_secrets: bool = False
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for radio in radios:
        entry: dict[str, Any] = {
            "stack": radio.get("__stack"),
            "interface": radio.get("name"),
            "band": radio.get("X_TP_Band"),
            "enabled": _bool(radio.get("enable")),
            "status": radio.get("status"),
            "ssid": radio.get("SSID"),
            "bssid": radio.get("BSSID"),
            "hidden": radio.get("SSIDAdvertisementEnabled") == "0",
            "channel": _int(radio.get("channel")),
            "autoChannel": _bool(radio.get("autoChannelEnable")),
            "bandwidth": radio.get("X_TP_Bandwidth"),
            "standard": radio.get("standard"),
            "security": _describe_security(radio),
            "transmitPower": _int(radio.get("transmitPower")),
            "maxClients": _int(radio.get("maxStaNum")),
            "isolateClients": _bool(radio.get("X_TP_IsolateClients")),
            "wmm": _bool(radio.get("WMMEnable")),
            "region": (radio.get("regulatoryDomain") or "").strip() or None,
        }
        if include_secrets:
            entry["passphrase"] = radio.get("X_TP_PreSharedKey")
        entries.append(entry)
    return entries


def _build_leases(hosts: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "ip": host.get("IPAddress"),
            "mac": _normalize_mac(host.get("MACAddress")),
            "hostname": host.get("hostName")
            if host.get("hostName") and host.get("hostName") != "Unknown"
            else None,
            "leaseTimeRemaining": _int(host.get("leaseTimeRemaining")),
            # X_TP_ConnType : 1 = sans fil, 0 = filaire
            "wireless": host.get("X_TP_ConnType") == "1",
        }
        for host in hosts
    ]


def _build_wireless_clients(
    devices: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    return [
        {
            "mac": _normalize_mac(device.get("associatedDeviceMACAddress")),
            "interface": device.get("X_TP_HostName"),
            "packetsSent": _int(device.get("X_TP_TotalPacketsSent")),
            "packetsReceived": _int(device.get("X_TP_TotalPacketsReceived")),
        }
        for device in devices
    ]


def _merge_clients(
    leases: Sequence[Mapping[str, Any]], wireless: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Fusionne baux DHCP et stations Wi-Fi, dédoublonnés par adresse MAC."""
    by_mac: dict[str, dict[str, Any]] = {}

    for lease in leases:
        if not lease["mac"]:
            continue
        by_mac[lease["mac"]] = {
            "mac": lease["mac"],
            "ip": lease["ip"],
            "hostname": lease["hostname"],
            "connection": "wireless" if lease["wireless"] else "wired",
            "leaseTimeRemaining": lease["leaseTimeRemaining"],
            "packetsSent": None,
            "packetsReceived": None,
        }

    for client in wireless:
        if not client["mac"]:
            continue
        existing = by_mac.get(client["mac"])
        if existing:
            existing["connection"] = "wireless"
            existing["interface"] = client["interface"]
            existing["packetsSent"] = client["packetsSent"]
            existing["packetsReceived"] = client["packetsReceived"]
        else:
            by_mac[client["mac"]] = {
                "mac": client["mac"],
                "ip": None,
                "hostname": None,
                "connection": "wireless",
                "interface": client["interface"],
                "leaseTimeRemaining": None,
                "packetsSent": client["packetsSent"],
                "packetsReceived": client["packetsReceived"],
            }

    return sorted(by_mac.values(), key=lambda c: _ip_sort_key(c.get("ip")))


class TpLinkRouter:
    """Routeur TP-Link, vu comme un ensemble de sections lisibles."""

    def __init__(
        self,
        *,
        host: str,
        password: str,
        username: str = "admin",
        timeout: float = 10.0,
        name: str | None = None,
    ) -> None:
        self.name = name or host
        self.session = TpLinkSession(
            host=host, password=password, username=username, timeout=timeout
        )

    @property
    def host(self) -> str:
        return self.session.host

    async def connect(self) -> bool:
        """Ouvre la session. Optionnel : les autres méthodes s'y connectent seules."""
        return await self.session.login()

    async def disconnect(self) -> None:
        """Ferme la session côté routeur. À appeler pour libérer le slot admin."""
        await self.session.logout()

    # -------------------------------------------------------- Informations --

    async def get_info(self) -> dict[str, Any]:
        """Modèle, versions, temps de fonctionnement et adresse MAC."""
        info, sys_cfg, mode = await asyncio.gather(
            self.session.get(OID.IGD_DEV_INFO, attrs=ATTRS_INFO),
            _safe(self.session.get(OID.SYS_CFG, attrs=["flashMac"]), None),
            _safe(self.session.get(OID.MULTIMODE, attrs=["mode"]), None),
        )
        return _build_info(self.host, info, sys_cfg, mode)

    # ----------------------------------------------------------------- LAN --

    async def get_lan(self) -> dict[str, Any]:
        """Adressage LAN et état du serveur DHCP."""
        intf, dhcp = await asyncio.gather(
            self.session.get_list(OID.LAN_IP_INTF, attrs=ATTRS_LAN_INTF),
            _safe(self.session.get_list(OID.LAN_HOST_CFG, attrs=["DHCPServerEnable"]), []),
        )

        return _build_lan(intf, dhcp)

    async def get_ethernet_ports(self) -> list[dict[str, Any]]:
        """Ports Ethernet du switch LAN."""
        ports = await self.session.get_list(
            OID.LAN_ETH_INTF, attrs=["status", "maxBitRate", "duplexMode"]
        )
        return [
            {
                "port": index + 1,
                "up": port.get("status") == "Up",
                "status": port.get("status"),
                "speed": port.get("maxBitRate"),
                "duplex": port.get("duplexMode"),
            }
            for index, port in enumerate(ports)
        ]

    # ----------------------------------------------------------------- WAN --

    async def get_wan(self) -> dict[str, Any]:
        """
        État de la connexion Internet.

        Le firmware déclare plusieurs profils WAN (IPoE statique, IPoE DHCP,
        PPPoE…) dont un seul est actif : on renvoie celui qui est activé et
        connecté.
        """
        ip_conns, ppp_conns, common, eth = await asyncio.gather(
            _safe(self.session.get_list(OID.WAN_IP_CONN, attrs=ATTRS_WAN_IP), []),
            _safe(self.session.get_list(OID.WAN_PPP_CONN, attrs=ATTRS_WAN_PPP), []),
            _safe(
                self.session.get_list(OID.WAN_COMMON_INTF_CFG, attrs=["WANAccessType"]),
                [],
            ),
            _safe(self.session.get_list(OID.WAN_ETH_INTF, attrs=ATTRS_ETH), []),
        )
        return _build_wan(ip_conns, ppp_conns, common, eth)

    # ---------------------------------------------------------------- Wi-Fi --

    async def get_wireless(self, *, include_secrets: bool = False) -> list[dict[str, Any]]:
        """
        Radios Wi-Fi et leur configuration.

        ``include_secrets`` ajoute la clé WPA en clair. Le firmware la renvoie
        systématiquement ; elle est masquée par défaut pour éviter de la
        propager dans les journaux ou dans les attributs d'une entité.
        """
        radios = await self.session.get_list(OID.LAN_WLAN)
        return _build_wireless(radios, include_secrets=include_secrets)

    async def _find_radio(self, band: str | int | None) -> dict[str, str] | None:
        """Radio par bande (``"2.4GHz"`` / ``"5GHz"``) ou par index."""
        radios = await self.session.get_list(
            OID.LAN_WLAN, attrs=["enable", "SSID", "X_TP_Band", "name"]
        )
        if band is None:
            return radios[0] if radios else None
        if isinstance(band, int) and not isinstance(band, bool):
            return radios[band] if 0 <= band < len(radios) else None

        wanted = "".join(str(band).lower().split())
        for radio in radios:
            if "".join((radio.get("X_TP_Band") or "").lower().split()) == wanted:
                return radio
            if (radio.get("name") or "").lower() == wanted:
                return radio
        return None

    async def set_wireless_enabled(
        self, enabled: bool, *, band: str | int | None = None
    ) -> dict[str, Any]:
        """Allume ou éteint une radio Wi-Fi. Première radio par défaut."""
        radio = await self._find_radio(band)
        if not radio:
            label = f" {band}" if band is not None else ""
            raise TpLinkError(f"Aucune radio Wi-Fi{label} sur {self.host}", host=self.host)

        await self.session.set(
            OID.LAN_WLAN, {"enable": 1 if enabled else 0}, stack=radio.get("__stack")
        )
        return {"band": radio.get("X_TP_Band"), "enabled": enabled}

    async def set_ssid(self, ssid: str, *, band: str | int | None = None) -> dict[str, Any]:
        """Change le SSID d'une radio."""
        if not ssid or len(ssid) > 32:
            raise TpLinkError("Le SSID doit faire entre 1 et 32 caractères")

        radio = await self._find_radio(band)
        if not radio:
            label = f" {band}" if band is not None else ""
            raise TpLinkError(f"Aucune radio Wi-Fi{label} sur {self.host}", host=self.host)

        await self.session.set(OID.LAN_WLAN, {"SSID": ssid}, stack=radio.get("__stack"))
        return {"band": radio.get("X_TP_Band"), "ssid": ssid}

    # -------------------------------------------------------------- Clients --

    async def get_dhcp_leases(self) -> list[dict[str, Any]]:
        """Baux DHCP en cours."""
        hosts = await self.session.get_list(OID.LAN_HOST_ENTRY, attrs=ATTRS_HOSTS)
        return _build_leases(hosts)

    async def get_wireless_clients(self) -> list[dict[str, Any]]:
        """Stations Wi-Fi associées."""
        devices = await self.session.get_list(OID.LAN_WLAN_ASSOC_DEV, attrs=ATTRS_ASSOC)
        return _build_wireless_clients(devices)

    async def get_clients(self) -> list[dict[str, Any]]:
        """
        Liste unifiée des appareils connectés : baux DHCP fusionnés avec les
        stations Wi-Fi associées, dédoublonnés par adresse MAC.

        C'est la vue utile pour le suivi de présence dans Home Assistant.
        """
        leases, wireless = await asyncio.gather(
            _safe(self.get_dhcp_leases(), []),
            _safe(self.get_wireless_clients(), []),
        )

        return _merge_clients(leases, wireless)

    # ------------------------------------------------------------- Synthèse --

    #: Le lot unique de :meth:`get_status`, dans l'ordre des résultats attendus.
    _STATUS_BATCH: Final = (
        (ACT.GET, OID.IGD_DEV_INFO, ATTRS_INFO),
        (ACT.GET, OID.SYS_CFG, ["flashMac"]),
        (ACT.GET, OID.MULTIMODE, ["mode"]),
        (ACT.GL, OID.LAN_IP_INTF, ATTRS_LAN_INTF),
        (ACT.GL, OID.LAN_HOST_CFG, ["DHCPServerEnable"]),
        (ACT.GL, OID.WAN_IP_CONN, ATTRS_WAN_IP),
        (ACT.GL, OID.WAN_PPP_CONN, ATTRS_WAN_PPP),
        (ACT.GL, OID.WAN_COMMON_INTF_CFG, ["WANAccessType"]),
        (ACT.GL, OID.WAN_ETH_INTF, ATTRS_ETH),
        (ACT.GL, OID.LAN_WLAN, None),
        (ACT.GL, OID.LAN_HOST_ENTRY, ATTRS_HOSTS),
        (ACT.GL, OID.LAN_WLAN_ASSOC_DEV, ATTRS_ASSOC),
    )

    async def get_status(self, *, include_secrets: bool = False) -> dict[str, Any]:
        """
        Instantané complet du routeur.

        Tout est lu en **une seule requête** : le firmware n'accepte qu'un
        administrateur connecté à la fois, et chaque nouvelle authentification
        invalide la session précédente. Enchaîner une douzaine de requêtes
        ouvrait autant d'occasions de se faire évincer par un navigateur ouvert
        sur l'interface web — d'où des sections vides, au hasard.

        Si le lot échoue malgré tout, on retombe sur des lectures section par
        section : plus lent, mais une section refusée n'emporte plus les autres.
        """
        try:
            return await self._status_batched(include_secrets=include_secrets)
        except TpLinkError as err:
            _LOGGER.debug(
                "Lot unique refusé par %s (%s) : lecture section par section",
                self.host,
                err,
            )
            return await self._status_per_section(include_secrets=include_secrets)

    async def _status_batched(self, *, include_secrets: bool) -> dict[str, Any]:
        actions = [
            Action(type=action_type, oid=oid, attrs=attrs)
            for action_type, oid, attrs in self._STATUS_BATCH
        ]
        results = (await self.session.execute(actions)).results

        info, sys_cfg, mode = (r[0] if r else None for r in results[:3])
        status = {
            "host": self.host,
            "name": self.name,
            "info": _build_info(self.host, info, sys_cfg, mode),
            "lan": _build_lan(results[3], results[4]),
            "wan": _build_wan(results[5], results[6], results[7], results[8]),
            "wireless": _build_wireless(results[9], include_secrets=include_secrets),
            "clients": _merge_clients(
                _build_leases(results[10]), _build_wireless_clients(results[11])
            ),
        }
        status["clientCount"] = len(status["clients"])
        return status

    async def _status_per_section(self, *, include_secrets: bool) -> dict[str, Any]:
        sections: dict[str, Callable[[], Any]] = {
            "info": self.get_info,
            "lan": self.get_lan,
            "wan": self.get_wan,
            "wireless": lambda: self.get_wireless(include_secrets=include_secrets),
            "clients": self.get_clients,
        }

        status: dict[str, Any] = {"host": self.host, "name": self.name}
        errors: dict[str, Any] = {}

        # Séquentiel et non `gather` : le firmware ne traite qu'une requête à la
        # fois, et une section en échec ne doit pas annuler les suivantes.
        for key, load in sections.items():
            try:
                status[key] = await load()
            except TpLinkError as err:
                status[key] = None
                errors[key] = err.to_dict()
            except Exception as err:  # noqa: BLE001
                status[key] = None
                errors[key] = {"message": str(err)}

        if errors:
            status["errors"] = errors

        clients = status.get("clients")
        status["clientCount"] = len(clients) if isinstance(clients, list) else None
        return status

    # ----------------------------------------------------------- Opérations --

    async def reboot(self) -> dict[str, Any]:
        """
        Redémarre le routeur.

        La connexion est coupée immédiatement : le firmware ne répond pas
        toujours avant de redémarrer, une absence de réponse n'est donc pas une
        erreur.
        """
        try:
            await self.session.execute(Action(ACT.OP, OP.REBOOT))
        except Exception as err:  # noqa: BLE001
            # Redémarrage engagé : le routeur ferme la socket sans répondre.
            if not is_disconnect_error(err):
                raise

        self.session.logged_in = False
        self.session.cookie = None
        return {"rebooting": True, "host": self.host}

    @property
    def raw(self) -> TpLinkSession:
        """Accès direct au modèle de données, pour tout ce que l'API haut niveau
        n'expose pas. Voir :class:`OID` pour les identifiants connus."""
        return self.session


def _describe_security(radio: Mapping[str, str]) -> dict[str, Any]:
    beacon = radio.get("beaconType")
    if beacon in ("11i", "WPAand11i"):
        auth = radio.get("IEEE11iAuthenticationMode") or ""
        return {
            "mode": "WPA2-PSK" if beacon == "11i" else "WPA/WPA2-PSK",
            "encryption": radio.get("IEEE11iEncryptionModes"),
            "enterprise": "EAP" in auth,
        }
    if beacon == "WPA":
        return {
            "mode": "WPA-PSK",
            "encryption": radio.get("WPAEncryptionModes"),
            "enterprise": "EAP" in (radio.get("WPAAuthenticationMode") or ""),
        }

    basic = radio.get("basicEncryptionModes")
    if basic and basic != "None":
        return {"mode": "WEP", "encryption": basic, "enterprise": False}

    return {"mode": "None", "encryption": None, "enterprise": False}
