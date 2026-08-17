"""
Client Python pour l'interface web des routeurs TP-Link « legacy »
(TL-WR841N v13/v14 et proches, firmwares exposant ``/cgi_gdpr``).

Portage du client JavaScript ``tplink`` (`src/core` + `src/api`), en asyncio afin
de pouvoir être appelé directement depuis Home Assistant sans bloquer la boucle
d'événements.

Usage :

.. code-block:: python

    from tplink_legacy.api import TpLinkRouter

    router = TpLinkRouter(host="192.168.0.1", password="…")
    try:
        print(await router.get_status())
        await router.set_wireless_enabled(False)
    finally:
        await router.disconnect()

Aucune méthode n'exige d'appeler :meth:`TpLinkRouter.connect` : la session
s'ouvre et se renouvelle seule. En revanche :meth:`TpLinkRouter.disconnect`
libère le slot administrateur du routeur, qui n'en a qu'un.
"""

from __future__ import annotations

from .error_codes import ERROR_CODES, error_name
from .errors import TpLinkAuthError, TpLinkError, TpLinkProtocolError
from .oids import OID
from .router import TpLinkRouter
from .rsa import rsa_encrypt_no_padding
from .session import ACT, OP, Action, TpLinkResponse, TpLinkSession

__all__ = [
    "ACT",
    "ERROR_CODES",
    "OID",
    "OP",
    "Action",
    "TpLinkAuthError",
    "TpLinkError",
    "TpLinkProtocolError",
    "TpLinkResponse",
    "TpLinkRouter",
    "TpLinkSession",
    "error_name",
    "rsa_encrypt_no_padding",
]
