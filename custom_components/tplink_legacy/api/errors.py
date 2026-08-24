"""Exceptions de la librairie — portage de ``src/core/errors.js``."""

from __future__ import annotations

from typing import Any

from .error_codes import ERROR_CODES, error_name

__all__ = [
    "ERROR_CODES",
    "error_name",
    "TpLinkError",
    "TpLinkAuthError",
    "TpLinkProtocolError",
    "TpLinkUnreachableError",
]


class TpLinkError(Exception):
    """Erreur générique remontée par la librairie."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        host: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: Code d'erreur du firmware, si connu.
        self.code = code
        #: Nom symbolique du code, extrait de ``err.js``.
        self.code_name = error_name(code)
        self.host = host
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        """Équivalent du ``toJSON()`` JS — sert à sérialiser dans ``get_status()``."""
        return {
            "error": type(self).__name__,
            "message": self.message,
            "code": self.code,
            "codeName": self.code_name,
            "host": self.host,
            "status": self.status,
        }


class TpLinkAuthError(TpLinkError):
    """Authentification refusée, ou session expirée."""


class TpLinkProtocolError(TpLinkError):
    """Réponse HTTP ou format inattendu (firmware non supporté, session perdue)."""


class TpLinkUnreachableError(TpLinkError):
    """Le routeur n'a pas répondu du tout : socket refusée, coupée, ou délai dépassé.

    À distinguer d'un refus applicatif : le routeur qui répond ``500`` sur une
    section peut en livrer d'autres, alors qu'un httpd muet ne livrera rien.
    Insister ne fait qu'aggraver son cas — ces firmwares ne tiennent qu'une
    poignée de sockets.
    """
