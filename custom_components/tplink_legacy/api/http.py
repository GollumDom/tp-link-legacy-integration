"""
Client HTTP minimal dédié au serveur web embarqué du routeur.

Portage de ``src/core/http.js``, en asyncio — une intégration Home Assistant ne
doit jamais bloquer la boucle d'événements, donc pas de ``socket`` synchrone ni
de ``requests``.

Pourquoi ne pas utiliser ``aiohttp`` (déjà présent dans Home Assistant) : le
httpd du routeur annonce ``Transfer-Encoding: chunked`` sur ses pages d'erreur
mais envoie le corps en clair. Tous les parseurs HTTP stricts échouent dessus
(« Invalid character in chunk size ») — c'était déjà le cas de ``fetch()`` et de
``node:http`` côté JS, y compris avec ``insecureHTTPParser``. On perd alors le
code de statut, c'est-à-dire la seule information utile pour diagnostiquer.

On parle donc HTTP/1.1 sur une socket brute, avec un parseur tolérant :
découpage chunked si possible, corps brut sinon.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Mapping

__all__ = ["HttpResponse", "request"]

HEADER_SEPARATOR = b"\r\n\r\n"
DEFAULT_PORT = 80


@dataclass(slots=True)
class HttpResponse:
    """Réponse brute du routeur."""

    status: int
    status_text: str
    headers: dict[str, str] = field(default_factory=dict)
    set_cookie: list[str] = field(default_factory=list)
    body: str = ""


async def request(
    *,
    host: str,
    path: str,
    method: str = "POST",
    headers: Mapping[str, str | int] | None = None,
    body: str | None = None,
    timeout: float = 10.0,
    port: int = DEFAULT_PORT,
) -> HttpResponse:
    """
    Envoie une requête et rend la réponse complète.

    ``timeout`` est en SECONDES (le JS l'exprimait en millisecondes) : c'est la
    convention d'``asyncio`` et de Home Assistant.
    """
    payload = b"" if body is None else body.encode("utf-8")

    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}"]
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {value}")
    lines.append(f"Content-Length: {len(payload)}")
    lines.append("Connection: close")

    head = ("\r\n".join(lines)).encode("utf-8") + HEADER_SEPARATOR

    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(host, port)
            try:
                writer.write(head + payload)
                await writer.drain()
                raw = await _read_response(reader)
            finally:
                writer.close()
                # Une socket fermée par le routeur en cours de route (cas du
                # redémarrage) fait lever `wait_closed()` : sans importance, la
                # réponse est déjà lue.
                try:
                    await writer.wait_closed()
                except (OSError, asyncio.IncompleteReadError):
                    pass
    except asyncio.TimeoutError as err:
        raise TimeoutError(f"timeout après {timeout} s") from err

    return _parse_response(raw)



async def _read_response(reader: asyncio.StreamReader) -> bytes:
    """Lit exactement une réponse, sans attendre la fermeture de la socket.

    Lire jusqu'à l'EOF paraît plus simple, mais ce httpd renvoie parfois une
    seconde réponse derrière la première : les deux se retrouvent alors
    concaténées, l'en-tête lu est celui de la première et le corps celui de la
    seconde — d'où un ``200 OK`` portant une page d'erreur. On s'arrête donc dès
    que le corps annoncé est complet.
    """
    raw = b""
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            return raw
        raw += chunk
        if _is_complete(raw):
            return raw


def _is_complete(raw: bytes) -> bool:
    """La réponse contient-elle déjà un corps complet ?"""
    split = raw.find(HEADER_SEPARATOR)
    if split == -1:
        return False

    head = raw[:split].lower()
    body = raw[split + len(HEADER_SEPARATOR) :]

    for line in head.split(b"\r\n"):
        if line.startswith(b"content-length:"):
            try:
                return len(body) >= int(line.split(b":", 1)[1].strip())
            except ValueError:
                return False

    if b"transfer-encoding:" in head and b"chunked" in head:
        # Terminateur de corps chunké. Le firmware annonce parfois `chunked`
        # sans l'appliquer sur ses pages d'erreur : on attend alors l'EOF.
        return raw.find(b"0\r\n\r\n", split) != -1

    return False


def _parse_response(raw: bytes) -> HttpResponse:
    split = raw.find(HEADER_SEPARATOR)
    if split == -1:
        raise ValueError("réponse HTTP tronquée (aucun en-tête complet reçu)")

    head_lines = raw[:split].decode("latin1").split("\r\n")
    status_line = head_lines[0]

    # `HTTP/1.1 404 Not Found` — le texte de statut peut être vide.
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
        raise ValueError(f"ligne de statut HTTP illisible : {status_line}")

    status = int(parts[1])
    status_text = parts[2] if len(parts) > 2 else ""

    headers: dict[str, str] = {}
    set_cookie: list[str] = []
    for line in head_lines[1:]:
        colon = line.find(":")
        if colon == -1:
            continue
        name = line[:colon].strip().lower()
        value = line[colon + 1 :].strip()
        if name == "set-cookie":
            set_cookie.append(value)
        else:
            headers[name] = value

    body_raw = raw[split + len(HEADER_SEPARATOR) :]

    transfer_encoding = headers.get("transfer-encoding", "").lower()
    if "chunked" in transfer_encoding:
        dechunked = _try_dechunk(body_raw)
        # Le routeur annonce parfois chunked sans l'appliquer : on garde le brut.
        if dechunked is not None:
            body_raw = dechunked
    elif "content-length" in headers:
        try:
            length = int(headers["content-length"])
        except ValueError:
            length = -1
        if 0 <= length <= len(body_raw):
            body_raw = body_raw[:length]

    return HttpResponse(
        status=status,
        status_text=status_text,
        headers=headers,
        set_cookie=set_cookie,
        # `errors="replace"` : le corps chiffré mal découpé ne doit pas faire
        # lever ici — c'est `_decrypt_body()` qui doit diagnostiquer, avec un
        # message parlant.
        body=body_raw.decode("utf-8", errors="replace"),
    )


def _try_dechunk(buffer: bytes) -> bytes | None:
    """Décode un corps ``Transfer-Encoding: chunked``.

    Rend ``None`` si le corps n'est pas réellement chunké — cas courant sur ce
    firmware, et c'est précisément ce que les parseurs stricts refusent.
    """
    parts: list[bytes] = []
    offset = 0

    while offset < len(buffer):
        eol = buffer.find(b"\r\n", offset)
        if eol == -1:
            return None

        header = buffer[offset:eol].split(b";")[0].strip()
        if not header:
            return None
        try:
            size = int(header, 16)
        except ValueError:
            return None

        if size == 0:
            return b"".join(parts)

        start = eol + 2
        end = start + size
        if end > len(buffer):
            return None

        parts.append(buffer[start:end])
        offset = end + 2  # saute le CRLF de fin de chunk

    return b"".join(parts) if parts else None
