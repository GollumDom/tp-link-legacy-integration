"""Connexion HTTP persistante vers le routeur.

Ces firmwares n'accordent l'accès aux données sensibles — Wi-Fi, clients, WAN —
qu'aux clients ayant ouvert une session « comme un navigateur » : page de login,
scripts, puis authentification, **le tout sur une seule connexion TCP maintenue
ouverte**. Une authentification menée sur des connexions séparées réussit
pourtant (``ret=0``, cookie, ``userType="Admin"``) mais n'obtient ensuite que le
modèle, le micrologiciel et le mode ; tout le reste répond ``HTTP 500``.

L'autorisation est mémorisée par le routeur pour le couple (adresse source,
routeur), et perdue à son redémarrage.
"""

from __future__ import annotations

import asyncio

DEFAULT_PORT = 80
HEADER_SEPARATOR = b"\r\n\r\n"

#: En-têtes d'un navigateur : ce sont eux que le firmware voit lors d'une
#: session d'interface web légitime.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)

#: Scripts chargés par la page de login, dans l'ordre où le navigateur les demande.
LOGIN_SCRIPTS = (
    "oid_str.js",
    "str.js",
    "err.js",
    "language.js",
    "root.js",
    "cryptoJS.min.js",
    "encrypt.js",
    "tpEncrypt.js",
    "lib.js",
)


class Response:
    __slots__ = ("status", "headers", "set_cookie", "body")

    def __init__(self, status, headers, set_cookie, body):
        self.status = status
        self.headers = headers
        self.set_cookie = set_cookie
        self.body = body


class Connection:
    """Une connexion TCP réutilisée pour plusieurs requêtes."""

    def __init__(self, host: str, *, port: int = DEFAULT_PORT, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.cookie: str | None = None
        #: Le routeur a renvoyé une réponse malformée : la connexion n'est plus sûre.
        self._degraded = False
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def __aenter__(self) -> Connection:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.timeout
        )
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._writer is None:
            return
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (OSError, asyncio.IncompleteReadError):
            pass

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        content_type: str | None = None,
    ) -> Response:
        payload = b"" if body is None else body.encode("utf-8")

        lines = [
            f"{method} {path} HTTP/1.1",
            f"Host: {self.host}",
            f"User-Agent: {USER_AGENT}",
            f"Referer: http://{self.host}/",
            f"Origin: http://{self.host}",
            # Le maintien de la connexion est le point essentiel : c'est lui qui
            # distingue une session d'interface web d'un simple appel d'API.
            "Connection: keep-alive",
        ]
        if content_type:
            lines.append(f"Content-Type: {content_type}")
        if self.cookie:
            lines.append(f"Cookie: {self.cookie}")
        lines.append(f"Content-Length: {len(payload)}")

        self._writer.write(("\r\n".join(lines)).encode() + HEADER_SEPARATOR + payload)
        await self._writer.drain()

        head = await asyncio.wait_for(
            self._reader.readuntil(HEADER_SEPARATOR), self.timeout
        )
        text = head.decode("latin1")
        status = int(text.split(" ", 2)[1])

        headers: dict[str, str] = {}
        set_cookie: list[str] = []
        for line in text.split("\r\n")[1:]:
            name, _, value = line.partition(":")
            name = name.strip().lower()
            if not name:
                continue
            if name == "set-cookie":
                set_cookie.append(value.strip())
            else:
                headers[name] = value.strip()

        for raw in set_cookie:
            if "JSESSIONID=" not in raw:
                continue
            value = raw.split("JSESSIONID=", 1)[1].split(";")[0]
            self.cookie = None if value in ("deleted", "") else f"JSESSIONID={value}"

        body_bytes = b""
        if "chunked" in headers.get("transfer-encoding", "").lower():
            while True:
                size_line = await asyncio.wait_for(self._reader.readline(), self.timeout)
                try:
                    size = int(size_line.strip() or b"0", 16)
                except ValueError:
                    # Le firmware annonce `chunked` sans l'appliquer sur ses pages
                    # d'erreur : on récupère ce qui vient et on ferme.
                    body_bytes += size_line
                    try:
                        body_bytes += await asyncio.wait_for(self._reader.read(65536), 1.0)
                    except (asyncio.TimeoutError, OSError):
                        pass
                    self._degraded = True
                    break
                if size == 0:
                    await self._reader.readline()
                    break
                body_bytes += await self._reader.readexactly(size)
                await self._reader.readline()
        elif "content-length" in headers:
            length = int(headers["content-length"])
            if length:
                body_bytes = await self._reader.readexactly(length)

        return Response(status, headers, set_cookie, body_bytes.decode("utf-8", "replace"))
