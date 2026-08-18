"""Constantes de l'intégration TP-Link Legacy."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "tplink_legacy"

CONF_INCLUDE_SECRETS: Final = "include_secrets"

DEFAULT_USERNAME: Final = "admin"
DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_TIMEOUT: Final = 10.0

MANUFACTURER: Final = "TP-Link"

PLATFORMS: Final = [
    "binary_sensor",
    "button",
    "device_tracker",
    "sensor",
    "switch",
]
