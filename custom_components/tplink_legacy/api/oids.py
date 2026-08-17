"""
Identifiants d'objets (OID) du modèle de données TP-Link.

Portage de ``src/core/oids.js``. Relevés dans ``js/oid_str.js`` servi par le
routeur. Seuls ceux réellement utilisés par la librairie sont repris ici ;
:meth:`TpLinkSession.get` accepte de toute façon n'importe quelle chaîne, le
firmware en expose plusieurs centaines.
"""

from __future__ import annotations

from typing import Final

__all__ = ["OID"]


class OID:
    """Constantes d'OID. Classe plutôt que dict : l'accès par attribut est
    vérifiable statiquement, là où ``OID["TYPO"]`` ne casserait qu'à l'exécution."""

    # Informations système
    IGD: Final = "IGD"
    IGD_DEV_INFO: Final = "IGD_DEV_INFO"
    SYS_CFG: Final = "SYS_CFG"
    SYS_MODE: Final = "SYS_MODE"
    MULTIMODE: Final = "MULTIMODE"
    ETH_SWITCH: Final = "ETH_SWITCH"

    # LAN
    LAN_IP_INTF: Final = "LAN_IP_INTF"
    LAN_HOST_CFG: Final = "LAN_HOST_CFG"
    LAN_HOST_ENTRY: Final = "LAN_HOST_ENTRY"
    LAN_ETH_INTF: Final = "LAN_ETH_INTF"
    LAN_DHCP_STATIC_ADDR: Final = "LAN_DHCP_STATIC_ADDR"

    # Wi-Fi
    LAN_WLAN: Final = "LAN_WLAN"
    LAN_WLAN_ASSOC_DEV: Final = "LAN_WLAN_ASSOC_DEV"
    LAN_WLAN_MULTISSID: Final = "LAN_WLAN_MULTISSID"
    LAN_WLAN_MSSIDENTRY: Final = "LAN_WLAN_MSSIDENTRY"
    LAN_WLAN_GUESTNET: Final = "LAN_WLAN_GUESTNET"

    # WAN
    WAN_COMMON_INTF_CFG: Final = "WAN_COMMON_INTF_CFG"
    WAN_ETH_INTF: Final = "WAN_ETH_INTF"
    WAN_IP_CONN: Final = "WAN_IP_CONN"
    WAN_PPP_CONN: Final = "WAN_PPP_CONN"

    # Divers
    L2_BRIDGING_ENTRY: Final = "L2_BRIDGING_ENTRY"
