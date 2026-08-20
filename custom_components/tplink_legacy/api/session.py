"""
Session bas niveau vers l'interface web TP-Link (TL-WR841N v13/v14 et proches,
firmwares exposant ``/cgi_gdpr``).

Portage de ``src/core/session.js``, en asyncio.

Le protocole est celui de ``js/lib.js`` + ``js/tpEncrypt.js`` servis par le
routeur :

1. POST ``/cgi?8`` avec ``[/cgi/getParm#…]0,0`` → renvoie ``nn`` / ``ee`` (clé
   publique RSA 512 bits) et ``seq`` (compteur de session).
2. On tire une clé AES-128-CBC et un IV (16 chiffres chacun, comme le firmware).
3. Chaque requête est postée sur ``/cgi_gdpr`` sous la forme
   ``sign=<hex RSA>\\r\\ndata=<base64 AES>\\r\\n`` où ``data`` chiffre le corps
   ``<types>\\r\\n[<oid>#<stack>#<pStack>]<index>,<n>\\r\\n<attributs>``
   et ``sign`` chiffre ``key=…&iv=…&h=md5(user+pwd)&s=<seq+len(data)>``.
4. La réponse est du base64 AES, à déchiffrer avec la même clé.

Toutes les requêtes exigent un en-tête ``Referer`` : sinon le routeur répond 403.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
from typing import Any, Final, Iterable, Mapping, Sequence

from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .error_codes import error_name
from .connection import Connection, LOGIN_SCRIPTS
from .errors import TpLinkAuthError, TpLinkError, TpLinkProtocolError
from .http import request

__all__ = ["ACT", "OP", "Action", "TpLinkResponse", "TpLinkSession"]


class ACT:
    """Types d'action, cf. l'en-tête de ``js/lib.js``."""

    GET: Final = 1
    SET: Final = 2
    ADD: Final = 3
    DEL: Final = 4
    GL: Final = 5  # get list
    GS: Final = 6  # get sub-list
    OP: Final = 7  # opération
    CGI: Final = 8
    SIG: Final = 9


class OP:
    """Opérations acceptées par :attr:`ACT.OP`."""

    REBOOT: Final = "ACT_REBOOT"
    FACTORY_RESET: Final = "ACT_FACTORY_RESET"


DEFAULT_STACK: Final = "0,0,0,0,0,0"

#: Codes renvoyés quand la session n'est plus valable → on retente une fois.
#: 71145 (ERR_USER_NOT_LOGIN) n'est pas dans la table de ``err.js`` : le firmware
#: l'émet sans le déclarer, d'où sa présence en dur ici comme dans le JS.
SESSION_ERRORS: Final = frozenset({-40101, -40102, -40103, -40104, -40401, 71145})

#: Fragments de message signalant que le routeur a coupé la connexion : attendu
#: pendant un redémarrage, ce n'est pas une erreur.
_DISCONNECT_HINTS: Final = ("injoignable", "timeout", "socket", "connection reset", "econnreset")


def _random_digits(length: int) -> str:
    """Chaîne de ``length`` chiffres décimaux — même forme que le firmware.

    ``secrets`` plutôt que ``random`` : cette valeur est la clé AES de la session.
    """
    return "".join(secrets.choice("0123456789") for _ in range(length))


class Action(dict):
    """Une action du CGI. ``dict`` pour rester aussi souple que l'objet JS."""

    def __init__(
        self,
        type: int,
        oid: str,
        *,
        stack: str | None = None,
        p_stack: str | None = None,
        attrs: Mapping[str, Any] | Sequence[str] | None = None,
    ) -> None:
        super().__init__(type=type, oid=oid, stack=stack, p_stack=p_stack, attrs=attrs)


class TpLinkResponse:
    """Résultat d'un :meth:`TpLinkSession.execute`."""

    __slots__ = ("ret", "results", "script")

    def __init__(self, ret: int, results: list[list[dict[str, str]]], script: str) -> None:
        self.ret = ret
        self.results = results
        self.script = script


class TpLinkSession:
    """Session vers un routeur. Une instance = une session administrateur."""

    def __init__(
        self,
        *,
        host: str,
        password: str,
        username: str = "admin",
        timeout: float = 10.0,
    ) -> None:
        if not host:
            raise TpLinkError("`host` est requis")
        if password is None:
            raise TpLinkError("`password` est requis")

        cleaned = str(host)
        for prefix in ("http://", "https://"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
        self.host = cleaned.rstrip("/")
        self.base_url = f"http://{self.host}"
        self.username = username
        self.password = password
        self.timeout = timeout

        self.cookie: str | None = None
        self.aes_key: str | None = None
        self.aes_iv: str | None = None
        self.hash: str | None = None
        self.seq: int | None = None
        self.rsa_n: str | None = None
        self.rsa_e: str | None = None

        self.logged_in = False

        # Le firmware n'accepte qu'un administrateur connecté à la fois et ne
        # supporte pas les requêtes concurrentes : on sérialise tout. Le JS
        # chaînait des promesses ; un `Lock` dit la même chose en plus clair.
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- HTTP --

    async def _http(self, path: str, body: str | None) -> str:
        headers: dict[str, str] = {
            "Content-Type": "text/plain",
            "Referer": f"{self.base_url}/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) tp-link-api",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie

        try:
            res = await request(
                host=self.host,
                path=path,
                method="POST",
                headers=headers,
                body=body,
                timeout=self.timeout,
            )
        except Exception as err:  # noqa: BLE001 — on ré-emballe tout échec réseau
            raise TpLinkError(
                f"Routeur {self.host} injoignable : {err}",
                host=self.host,
            ) from err

        for raw in res.set_cookie:
            stripped = raw.strip()
            if not stripped.startswith("JSESSIONID="):
                continue
            value = stripped[len("JSESSIONID=") :].split(";")[0]
            # Sur erreur, le routeur renvoie `JSESSIONID=deleted; Expires=1970…` :
            # c'est une invalidation de session, pas un nouveau cookie.
            if value in ("deleted", ""):
                self.cookie = None
                self.logged_in = False
            else:
                self.cookie = f"JSESSIONID={value}"

        if res.status == 403:
            raise TpLinkError(
                f"403 sur {path} — le routeur {self.host} a refusé la requête "
                "(en-tête Referer manquant ?)",
                host=self.host,
                status=403,
            )
        if not 200 <= res.status < 300:
            # Le firmware répond 500 quand la session est perdue ou la requête invalide.
            raise TpLinkProtocolError(
                f"HTTP {res.status} sur {path} (routeur {self.host})",
                host=self.host,
                status=res.status,
            )
        return res.body

    # ---------------------------------------------------------- Chiffrement --

    def _encrypt_body(self, plaintext: str) -> str:
        """
        Chiffre un corps de requête.

        La signature embarque **toujours** la clé AES (``key=…&iv=…``), y compris
        hors login. Le firmware propose bien une forme courte (``h=…&s=…``, cf.
        ``getSignature(seq, isLogin)`` dans ``tpEncrypt.js``), mais elle suppose
        que le routeur a encore la clé de la session en mémoire : dès que ce
        contexte est perdu — et il l'est dès qu'une autre session est ouverte —
        le routeur répond ``500 Internal Server Error`` et invalide le cookie.
        Rejouer la forme complète à chaque requête rend la session autoportante.
        """
        assert self.aes_key and self.aes_iv and self.rsa_n and self.rsa_e

        padder = sym_padding.PKCS7(algorithms.AES.block_size).padder()
        padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()

        encryptor = Cipher(
            algorithms.AES(self.aes_key.encode("utf-8")),
            modes.CBC(self.aes_iv.encode("utf-8")),
        ).encryptor()
        data = base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")

        sign_plain = (
            f"key={self.aes_key}&iv={self.aes_iv}"
            f"&h={self.hash}&s={(self.seq or 0) + len(data)}"
        )
        # Import tardif volontaire : garde `rsa` remplaçable dans les tests.
        from .rsa import rsa_encrypt_no_padding

        sign = rsa_encrypt_no_padding(sign_plain, self.rsa_n, self.rsa_e)
        return f"sign={sign}\r\ndata={data}\r\n"

    def _decrypt_body(self, b64: str) -> str:
        assert self.aes_key and self.aes_iv

        decryptor = Cipher(
            algorithms.AES(self.aes_key.encode("utf-8")),
            modes.CBC(self.aes_iv.encode("utf-8")),
        ).decryptor()
        raw = decryptor.update(base64.b64decode(b64.strip())) + decryptor.finalize()

        unpadder = sym_padding.PKCS7(algorithms.AES.block_size).unpadder()
        return (unpadder.update(raw) + unpadder.finalize()).decode("utf-8")

    # ------------------------------------------------ Sérialisation du CGI --

    @staticmethod
    def build_payload(actions: Sequence[Mapping[str, Any]]) -> str:
        """
        Sérialise une liste d'actions au format attendu par ``$.exe()``.

        ``attrs`` suit la convention de ``$.toStr()`` du firmware :

        - séquence → liste de noms d'attributs à lire (:attr:`ACT.GET` / :attr:`ACT.GL`) ;
        - mapping  → paires ``clé=valeur`` à écrire (:attr:`ACT.SET` / :attr:`ACT.CGI`).
        """
        types = "&".join(str(action["type"]) for action in actions)
        body = ""

        for index, action in enumerate(actions):
            stack = action.get("stack") or DEFAULT_STACK
            p_stack = action.get("p_stack") or DEFAULT_STACK
            attrs_value = action.get("attrs")

            attrs = ""
            count = 0
            if isinstance(attrs_value, Mapping):
                for key, value in attrs_value.items():
                    attrs += f"{key}={value}\r\n"
                    count += 1
            elif isinstance(attrs_value, Iterable) and not isinstance(attrs_value, (str, bytes)):
                for name in attrs_value:
                    attrs += f"{name}\r\n"
                    count += 1

            body += f"[{action['oid']}#{stack}#{p_stack}]{index},{count}\r\n{attrs}"

        return f"{types}\r\n{body}"

    @staticmethod
    def parse_response(text: str, actions: Sequence[Mapping[str, Any]]) -> TpLinkResponse:
        """
        Parse la réponse déchiffrée, en suivant ``resolve()`` de ``js/lib.js``.

        Format : des en-têtes ``[<stack>]<index>`` suivis de lignes ``clé=valeur``,
        un bloc ``[cgi]`` contenant du JavaScript, et un ``[error]<code>`` final.
        """
        results: list[list[dict[str, str]]] = [[] for _ in actions]
        script = ""
        current: dict[str, str] | None = None
        current_stack: str | None = None
        ret = 0

        for raw_line in text.split("\n"):
            line = raw_line.rstrip("\r")
            if line == "":
                continue

            if line.startswith("["):
                close = line.find("]")
                if close == -1:
                    continue
                stack = line[1:close]
                tail = line[close + 1 :].strip()
                try:
                    index = int(tail)
                except ValueError:
                    index = 0

                if stack == "error":
                    if index:
                        ret = index
                    current = None
                    current_stack = "error"
                    continue

                current_stack = stack
                if stack == "cgi":
                    current = None
                    continue

                current = {"__stack": stack}
                if 0 <= index < len(results):
                    results[index].append(current)
                continue

            if current_stack == "cgi":
                script += line + "\n"
                continue
            if current is None:
                continue

            eq = line.find("=")
            if eq == -1:
                continue
            current[line[:eq]] = line[eq + 1 :]

        # Les blocs CGI signalent leur statut via `$.ret=<n>;`
        if ret == 0 and script:
            import re

            match = re.search(r"\$\.ret\s*=\s*(-?\d+)", script)
            if match and int(match.group(1)) != 0:
                ret = int(match.group(1))

        return TpLinkResponse(ret, results, script)

    # ---------------------------------------------------------------- Auth --

    async def fetch_params(self) -> dict[str, Any]:
        """Récupère ``nn`` / ``ee`` / ``seq``. Non chiffré, pas d'authentification."""
        import re

        payload = f"[/cgi/getParm#{DEFAULT_STACK}#{DEFAULT_STACK}]0,0\r\n"
        text = await self._http("/cgi?8", payload)

        nn = re.search(r'var nn\s*=\s*"([^"]+)"', text)
        ee = re.search(r'var ee\s*=\s*"([^"]+)"', text)
        seq = re.search(r'var seq\s*=\s*"?(\d+)"?', text)

        if not (nn and ee and seq):
            raise TpLinkProtocolError(
                f"Réponse /cgi/getParm inattendue sur {self.host} — firmware non supporté",
                host=self.host,
            )

        self.rsa_n = nn.group(1)
        self.rsa_e = ee.group(1)
        self.seq = int(seq.group(1))
        return {"nn": self.rsa_n, "ee": self.rsa_e, "seq": self.seq}

    async def login(self) -> bool:
        """
        Ouvre une session, en imitant le parcours d'un navigateur.

        La page de login, ses scripts et l'authentification sont envoyés sur
        **une seule connexion TCP maintenue ouverte**. C'est indispensable : une
        authentification menée sur des connexions séparées réussit — ``ret=0``,
        cookie, ``userType="Admin"`` — mais n'obtient ensuite que le modèle, le
        micrologiciel et le mode, tout le reste répondant ``HTTP 500``. Le
        routeur mémorise l'autorisation pour le couple (adresse source, routeur)
        et la perd à son redémarrage.

        ⚠️ Le firmware verrouille l'interface deux heures après dix échecs
        consécutifs : vérifiez le mot de passe avant de boucler.
        """
        self.cookie = None
        self.logged_in = False

        try:
            async with Connection(self.host, timeout=self.timeout) as conn:
                # 1. la page de login et ses scripts, comme le ferait un navigateur
                await conn.request("GET", "/")
                for script in LOGIN_SCRIPTS:
                    await conn.request("GET", f"/js/{script}")

                # 2. les paramètres de chiffrement
                params = await conn.request(
                    "POST",
                    "/cgi?8",
                    body=f"[/cgi/getParm#{DEFAULT_STACK}#{DEFAULT_STACK}]0,0\r\n",
                    content_type="text/plain",
                )
                self._read_params(params.body)

                self.aes_key = _random_digits(16)
                self.aes_iv = _random_digits(16)
                self.hash = hashlib.md5(
                    (self.username + self.password).encode("utf-8")
                ).hexdigest()

                # 3. l'authentification, sur cette même connexion
                actions = [
                    Action(
                        type=ACT.CGI,
                        oid="/cgi/login",
                        attrs={"username": self.username, "password": self.password},
                    )
                ]
                answer = await conn.request(
                    "POST",
                    "/cgi_gdpr",
                    body=self._encrypt_body(self.build_payload(actions)),
                    content_type="text/plain",
                )
                self.cookie = conn.cookie

                if answer.status != 200 or not self.cookie:
                    raise TpLinkAuthError(
                        f"Login refusé sur {self.host} "
                        f"(HTTP {answer.status}, mot de passe incorrect "
                        f"ou interface verrouillée après 10 échecs)",
                        host=self.host,
                    )

                try:
                    decrypted = self._decrypt_body(answer.body)
                except Exception as err:
                    raise TpLinkAuthError(
                        f"Login refusé sur {self.host} : réponse illisible",
                        host=self.host,
                    ) from err

                ret = self.parse_response(decrypted, actions).ret
                if ret != 0:
                    raise TpLinkAuthError(
                        f"Login refusé sur {self.host} : {_describe_code(ret)}",
                        host=self.host,
                        code=ret,
                    )

                # 4. la frame d'administration, puis une première lecture
                #    protégée sur cette même connexion : c'est elle qui scelle
                #    l'autorisation côté routeur.
                await conn.request("GET", "/mainFrame.htm")
                try:
                    await conn.request(
                        "POST",
                        "/cgi_gdpr",
                        body=self._encrypt_body(
                            self.build_payload(
                                [Action(type=ACT.GL, oid="LAN_WLAN", attrs=["SSID"])]
                            )
                        ),
                        content_type="text/plain",
                    )
                except Exception:  # noqa: BLE001
                    # Le routeur peut la refuser ; le login reste valable.
                    pass

        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
            raise TpLinkError(
                f"Routeur {self.host} injoignable : {err}", host=self.host
            ) from err

        self.logged_in = True
        return True

    def _read_params(self, body: str) -> None:
        """Extrait ``nn`` / ``ee`` / ``seq`` de la réponse de ``/cgi/getParm``."""
        nn = re.search(r'var nn\s*=\s*"([^"]+)"', body)
        ee = re.search(r'var ee\s*=\s*"([^"]+)"', body)
        seq = re.search(r'var seq\s*=\s*"?(\d+)"?', body)
        if not (nn and ee and seq):
            raise TpLinkProtocolError(
                f"Réponse /cgi/getParm inattendue sur {self.host} — "
                "firmware non supporté",
                host=self.host,
            )
        self.rsa_n, self.rsa_e, self.seq = nn.group(1), ee.group(1), int(seq.group(1))

    async def logout(self) -> None:
        """Ferme la session côté routeur (libère le slot administrateur)."""
        if not self.logged_in:
            return
        self.logged_in = False
        try:
            actions = [Action(ACT.CGI, "/cgi/logout")]
            body = self._encrypt_body(self.build_payload(actions))
            await self._http("/cgi_gdpr", body)
        except Exception:  # noqa: BLE001
            # Le routeur coupe parfois la connexion avant de répondre : sans importance.
            pass
        self.cookie = None

    # ----------------------------------------------------------- Exécution --

    async def _send(self, actions: Sequence[Mapping[str, Any]]) -> TpLinkResponse:
        body = self._encrypt_body(self.build_payload(actions))
        raw = await self._http("/cgi_gdpr", body)

        try:
            decrypted = self._decrypt_body(raw)
        except Exception as err:  # noqa: BLE001
            raise TpLinkAuthError(
                f"Session invalide sur {self.host} (réponse non déchiffrable)",
                host=self.host,
            ) from err
        return self.parse_response(decrypted, actions)

    async def execute(
        self, actions: Sequence[Mapping[str, Any]] | Mapping[str, Any]
    ) -> TpLinkResponse:
        """
        Exécute une ou plusieurs actions, en (re)connectant la session au besoin.
        Les appels sont sérialisés par session.
        """
        actions_list: Sequence[Mapping[str, Any]]
        actions_list = [actions] if isinstance(actions, Mapping) else list(actions)

        async with self._lock:
            if not self.logged_in:
                await self.login()

            try:
                response = await self._send(actions_list)
            except (TpLinkAuthError, TpLinkProtocolError):
                # Session perdue : le routeur répond 500 ou renvoie du binaire illisible.
                self.logged_in = False
                await self.login()
                response = await self._send(actions_list)

            if response.ret in SESSION_ERRORS:
                self.logged_in = False
                await self.login()
                response = await self._send(actions_list)

            if response.ret != 0:
                raise TpLinkError(
                    f"Le routeur {self.host} a refusé la requête : "
                    f"{_describe_code(response.ret)}",
                    host=self.host,
                    code=response.ret,
                )
            return response

    async def get(
        self,
        oid: str,
        *,
        stack: str | None = None,
        p_stack: str | None = None,
        attrs: Mapping[str, Any] | Sequence[str] | None = None,
    ) -> dict[str, str] | None:
        """Lecture d'un objet unique (:attr:`ACT.GET`)."""
        response = await self.execute(
            Action(ACT.GET, oid, stack=stack, p_stack=p_stack, attrs=attrs)
        )
        return response.results[0][0] if response.results[0] else None

    async def get_list(
        self,
        oid: str,
        *,
        stack: str | None = None,
        p_stack: str | None = None,
        attrs: Mapping[str, Any] | Sequence[str] | None = None,
    ) -> list[dict[str, str]]:
        """Lecture d'une liste (:attr:`ACT.GL`)."""
        response = await self.execute(
            Action(ACT.GL, oid, stack=stack, p_stack=p_stack, attrs=attrs)
        )
        return response.results[0]

    async def get_sub_list(
        self,
        oid: str,
        *,
        stack: str | None = None,
        p_stack: str | None = None,
        attrs: Mapping[str, Any] | Sequence[str] | None = None,
    ) -> list[dict[str, str]]:
        """Lecture d'une sous-liste rattachée à un parent (:attr:`ACT.GS`)."""
        response = await self.execute(
            Action(ACT.GS, oid, stack=stack, p_stack=p_stack, attrs=attrs)
        )
        return response.results[0]

    async def set(
        self,
        oid: str,
        attrs: Mapping[str, Any],
        *,
        stack: str | None = None,
        p_stack: str | None = None,
    ) -> bool:
        """Écriture d'attributs (:attr:`ACT.SET`)."""
        await self.execute(Action(ACT.SET, oid, stack=stack, p_stack=p_stack, attrs=attrs))
        return True

    async def op(
        self,
        oid: str,
        *,
        stack: str | None = None,
        p_stack: str | None = None,
        attrs: Mapping[str, Any] | Sequence[str] | None = None,
    ) -> bool:
        """Opération (:attr:`ACT.OP`), par exemple un redémarrage."""
        await self.execute(Action(ACT.OP, oid, stack=stack, p_stack=p_stack, attrs=attrs))
        return True


def _describe_code(code: int) -> str:
    name = error_name(code)
    return f"{name} ({code})" if name else f"code {code}"


def is_disconnect_error(err: Exception) -> bool:
    """Le routeur a-t-il simplement coupé la connexion ? (attendu au redémarrage)"""
    message = str(err).lower()
    return any(hint in message for hint in _DISCONNECT_HINTS)
