# API Python — `tplink_legacy.api`

Client asynchrone pour l'interface web des routeurs TP-Link « legacy »
(TL-WR841N v13/v14 et proches, firmwares exposant `/cgi_gdpr`).

C'est le portage du client JavaScript `Works/JS/tplink` — voir
[PORTAGE.md](PORTAGE.md) pour la correspondance fichier par fichier et les
écarts assumés.

## Pourquoi asyncio

Une intégration Home Assistant tourne dans une boucle d'événements unique et
partagée : le moindre appel réseau bloquant y gèle toute l'instance. Toutes les
méthodes d'entrée/sortie sont donc des coroutines.

## Dépendances

- Python ≥ 3.11 (`asyncio.timeout`)
- `cryptography` — déjà présent dans Home Assistant

Le RSA n'a besoin d'aucune bibliothèque : `pow(base, exp, mod)` et les entiers de
précision arbitraire de Python suffisent.

## Prise en main

```python
from tplink_legacy.api import TpLinkRouter

router = TpLinkRouter(host="192.168.0.1", password="motdepasse")
try:
    status = await router.get_status()
    print(status["info"]["model"], status["clientCount"], "appareils")
finally:
    await router.disconnect()
```

Aucune méthode n'exige un `connect()` préalable : la session s'ouvre et se
renouvelle seule.

> ⚠️ **Appelez toujours `disconnect()`.** Le firmware n'accepte **qu'un seul
> administrateur connecté à la fois**. Une session laissée ouverte empêche la
> connexion depuis un navigateur, et inversement.

> ⚠️ **Le firmware verrouille l'interface 2 heures après 10 échecs de mot de
> passe consécutifs.** Ne bouclez jamais sur un login qui échoue.

## `TpLinkRouter`

```python
TpLinkRouter(*, host, password, username="admin", timeout=10.0, name=None)
```

| Paramètre  | Détail |
|---|---|
| `host`     | IP ou nom d'hôte. Le préfixe `http://` est toléré et retiré. |
| `password` | Mot de passe de l'interface web. |
| `username` | `admin` sur toute la gamme. |
| `timeout`  | En **secondes** (le client JS l'exprimait en millisecondes). |
| `name`     | Libellé facultatif ; vaut `host` par défaut. |

### Lecture

| Méthode | Rend |
|---|---|
| `get_info()` | modèle, description, versions logicielle et matérielle, `uptime`, MAC, mode |
| `get_lan()` | IP, masque, MAC, `dhcpEnabled` |
| `get_ethernet_ports()` | un objet par port : `port`, `up`, `status`, `speed`, `duplex` |
| `get_wan()` | `connected`, `status`, `protocol`, `ip`, `gateway`, `dns[]`, `uptime`, `link` |
| `get_wireless(include_secrets=False)` | une entrée par radio |
| `get_dhcp_leases()` | baux DHCP |
| `get_wireless_clients()` | stations Wi-Fi associées |
| `get_clients()` | **vue unifiée**, baux + stations fusionnés par MAC |
| `get_status(include_secrets=False)` | tout ce qui précède, en un objet |

### Écriture et opérations

| Méthode | Effet |
|---|---|
| `set_wireless_enabled(enabled, *, band=None)` | allume ou éteint une radio |
| `set_ssid(ssid, *, band=None)` | change le SSID (1 à 32 caractères) |
| `reboot()` | redémarre le routeur |
| `connect()` / `disconnect()` | ouvre / ferme la session |

`band` accepte `"2.4GHz"`, `"5GHz"`, le nom d'interface (`"wlan0"`), ou un index
entier. Sans `band`, la première radio est visée.

### `get_status()` — la méthode conçue pour Home Assistant

Chaque section est isolée : **une section indisponible sur un firmware donné
renvoie son erreur sans faire échouer l'ensemble**.

```python
{
  "host": "192.168.0.1", "name": "192.168.0.1",
  "info": {...}, "lan": {...}, "wan": {...},
  "wireless": [...], "clients": [...],
  "clientCount": 7,
  "errors": {"wan": {"error": "TpLinkError", "message": "...", "code": None}},
}
```

La clé `errors` n'apparaît que si au moins une section a échoué.

### La clé Wi-Fi n'est jamais exposée par défaut

Le firmware renvoie `X_TP_PreSharedKey` **en clair** à chaque lecture de radio.
`get_wireless()` la retire ; il faut `include_secrets=True` pour l'obtenir.
Cela évite qu'elle se retrouve dans un journal ou dans les attributs d'une entité.

## Accès bas niveau

Pour ce que l'API haut niveau n'expose pas, `router.raw` donne la session :

```python
from tplink_legacy.api import OID

radios = await router.raw.get_list(OID.LAN_WLAN)
await router.raw.set(OID.LAN_WLAN, {"channel": 6}, stack="1,0,0,0,0,0")
```

| Méthode | Action CGI |
|---|---|
| `get(oid, *, stack, p_stack, attrs)` | `ACT.GET` |
| `get_list(...)` | `ACT.GL` |
| `get_sub_list(...)` | `ACT.GS` |
| `set(oid, attrs, *, stack, p_stack)` | `ACT.SET` |
| `op(oid, ...)` | `ACT.OP` |
| `execute(actions)` | plusieurs actions en une requête |

`attrs` suit la convention de `$.toStr()` du firmware : une **séquence** liste
les attributs à lire, un **mapping** donne les paires à écrire.

`OID` ne recense que les identifiants utilisés par la librairie ; le firmware en
expose plusieurs centaines et toute chaîne est acceptée.

## Erreurs

| Exception | Cas |
|---|---|
| `TpLinkError` | erreur générique ; porte `code`, `code_name`, `host`, `status` |
| `TpLinkAuthError` | mot de passe refusé, session expirée, réponse indéchiffrable |
| `TpLinkProtocolError` | HTTP inattendu, firmware non supporté |

`error_name(code)` traduit un code du firmware en nom symbolique (670 codes
relevés dans `err.js`). Certains codes émis par le firmware n'y figurent pas —
`71145` (`ERR_USER_NOT_LOGIN`) notamment ; `error_name()` rend alors `None`.

## Le protocole, en résumé

1. `POST /cgi?8` → clé publique RSA (`nn`, `ee`) et compteur `seq`.
2. Tirage d'une clé AES-128-CBC et d'un IV (16 chiffres chacun).
3. Chaque requête est postée sur `/cgi_gdpr` :
   `sign=<hex RSA>\r\ndata=<base64 AES>\r\n`.
4. La réponse est du base64 AES.

Deux détails qui coûtent cher si on les rate :

- **L'en-tête `Referer` est obligatoire** — sans lui, le routeur répond 403.
- **La signature embarque toujours la clé AES** (`key=…&iv=…`), y compris hors
  login. La forme courte proposée par le firmware suppose qu'il a encore la clé
  en mémoire ; dès qu'une autre session s'ouvre, il répond 500 et invalide le
  cookie.

## Tests

```bash
python3 -m unittest discover -s tests
```

33 tests, sans dépendance et sans routeur. Les valeurs attendues des tests de
protocole ont été **produites par le client JavaScript** puis figées : ils
vérifient que le portage parle le même protocole que l'implémentation de
référence, pas seulement qu'il est cohérent avec lui-même.
