"""Détection des routeurs TP-Link « legacy » sur le réseau.

Ces firmwares n'exposent ni UPnP/SSDP ni mDNS : seul le port 80 est ouvert. En
revanche ils ont une signature fiable et sans identifiants — ``POST /cgi?8``
avec ``/cgi/getParm`` renvoie la clé publique RSA de session (``var nn=…``), ce
qu'aucun autre serveur web ne fait. C'est ce que l'on sonde ici.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Any

from .api import TpLinkSession
from .api.errors import TpLinkError

_LOGGER = logging.getLogger(__name__)

#: Adresses de passerelle courantes, en complément de celle réellement utilisée.
COMMON_GATEWAYS: tuple[str, ...] = (
    "192.168.0.1",
    "192.168.1.1",
    "192.168.2.1",
    "192.168.10.1",
    "10.0.0.1",
    "10.0.1.1",
    "172.16.0.1",
)

PROBE_TIMEOUT = 2.0
MAX_CONCURRENT_PROBES = 24


async def probe(host: str, *, timeout: float = PROBE_TIMEOUT) -> dict[str, Any] | None:
    """Le firmware attendu répond-il à cette adresse ?

    Ne demande aucune authentification : ``/cgi/getParm`` est public.

    :return: ``{"host": …, "seq": …}`` si c'est un routeur compatible, sinon ``None``.
    """
    session = TpLinkSession(host=host, password="", timeout=timeout)
    try:
        params = await session.fetch_params()
    except (TpLinkError, OSError, asyncio.TimeoutError):
        return None
    except Exception:  # noqa: BLE001 — une sonde ne doit jamais faire échouer l'appelant
        _LOGGER.debug("Sonde inattendue en échec sur %s", host, exc_info=True)
        return None
    return {"host": host, "seq": params.get("seq")}


def local_gateways() -> list[str]:
    """Passerelles plausibles, déduites des adresses locales de la machine.

    Home Assistant tourne presque toujours derrière le routeur à découvrir :
    la passerelle de son propre réseau est donc le meilleur candidat.
    """
    candidates: list[str] = []

    try:
        with open("/proc/net/route", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    packed = bytes.fromhex(fields[2])[::-1]
                    candidates.append(socket.inet_ntoa(packed))
    except OSError:
        pass

    # À défaut, la première adresse du réseau de chaque interface.
    for address in _local_addresses():
        try:
            network = ipaddress.ip_network(f"{address}/24", strict=False)
        except ValueError:
            continue
        first = str(next(network.hosts()))
        if first not in candidates:
            candidates.append(first)

    return candidates


def _local_addresses() -> list[str]:
    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        return []
    return [a for a in addresses if not a.startswith("127.")]


async def discover(extra_hosts: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Sonde les adresses plausibles et renvoie les routeurs compatibles."""
    seen: list[str] = []
    for host in (*local_gateways(), *COMMON_GATEWAYS, *extra_hosts):
        if host not in seen:
            seen.append(host)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

    async def guarded(host: str) -> dict[str, Any] | None:
        async with semaphore:
            return await probe(host)

    results = await asyncio.gather(*(guarded(host) for host in seen))
    found = [result for result in results if result]
    _LOGGER.debug("Détection : %s routeur(s) parmi %s adresses", len(found), len(seen))
    return found
