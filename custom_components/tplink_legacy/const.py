"""Constantes de l'intégration TP-Link Legacy."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "tplink_legacy"

CONF_INCLUDE_SECRETS: Final = "include_secrets"

#: Valeur sentinelle du sélecteur « autre adresse » à l'étape de détection.
MANUAL_HOST: Final = "__manual__"

DEFAULT_USERNAME: Final = "admin"
DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_TIMEOUT: Final = 10.0

MIN_SCAN_INTERVAL: Final = 10
#: Une heure. Le httpd de ces firmwares finit par ne plus répondre à force
#: de connexions, et seul un redémarrage le remet en marche : qui a un
#: routeur fragile doit pouvoir l'interroger rarement, pas seulement moins
#: souvent que toutes les dix minutes.
MAX_SCAN_INTERVAL: Final = 3600

MANUFACTURER: Final = "TP-Link"

PLATFORMS: Final = [
    "binary_sensor",
    "button",
    "device_tracker",
    "sensor",
    "switch",
]
