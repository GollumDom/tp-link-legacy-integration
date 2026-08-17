# Portage JavaScript → Python

Correspondance entre le client d'origine (`Works/JS/tplink`) et ce portage, et
liste des écarts assumés.

## Correspondance des fichiers

| JavaScript | Python | Note |
|---|---|---|
| `src/core/rsa.js` | `api/rsa.py` | `modPow` remplacé par `pow()` natif |
| `src/core/http.js` | `api/http.py` | `net.connect` → `asyncio.open_connection` |
| `src/core/session.js` | `api/session.py` | file de promesses → `asyncio.Lock` |
| `src/core/errors.js` | `api/errors.py` | |
| `src/core/errors-codes.js` | `api/error_codes.py` | transcription mécanique, 670 codes |
| `src/core/oids.js` | `api/oids.py` | objet gelé → classe de constantes |
| `src/api/router.js` | `api/router.py` | |

`tplink_client_fulljs/` n'est **pas** porté : cette première approche chargeait
les scripts du routeur dans une VM et devinait les OID par heuristique
(`_findConst(["WLAN_ENABLE", "WIRELESS_ENABLE", …])`, puis essai de plusieurs
formes de charge utile jusqu'à ce qu'une passe). `src/core` + `src/api` la
remplacent par une implémentation native du protocole, seule portable.

## Régénérer la table des codes d'erreur

`api/error_codes.py` ne se modifie pas à la main :

```bash
node -e '
import("/chemin/vers/tplink/src/core/errors-codes.js").then(m => {
  const entries = Object.entries(m.ERROR_CODES).sort((a,b)=>Number(a[0])-Number(b[0]));
  console.log(entries.map(([c,n]) => `    ${c}: ${JSON.stringify(n)},`).join("\n"));
});'
```

puis recoller le bloc entre `ERROR_CODES: dict[int, str] = {` et `}`.

## Écarts assumés

### 1. Tout est asynchrone

Home Assistant tourne dans une boucle d'événements unique : un appel réseau
bloquant y gèle l'instance entière. `asyncio` de bout en bout.

### 2. `timeout` en secondes

Le JS l'exprimait en millisecondes. La convention d'`asyncio` et de Home
Assistant est la seconde. **C'est le seul changement d'unité du portage** —
attention en transposant un appel.

### 3. Sérialisation par `Lock` plutôt que par chaîne de promesses

Le JS chaînait chaque appel sur `this._queue`. Un `asyncio.Lock` exprime la même
contrainte (le firmware ne supporte pas les requêtes concurrentes) de façon plus
directe, et libère correctement en cas d'exception.

### 4. `get_status()` est séquentiel

Le JS lançait déjà ses sections en série. C'est délibéré : la session sérialise
de toute façon, et une section en échec ne doit pas annuler les suivantes.

Attention : à l'intérieur d'une section, `asyncio.gather` est utilisé comme le
`Promise.all` du JS — mais la sérialisation reste garantie par le `Lock` de la
session, `gather` ne fait qu'ordonnancer l'attente.

### 5. Tri des clients par IP

Le JS s'appuyait sur `localeCompare(…, {numeric: true})`. Python n'a pas
d'équivalent direct : `_ip_sort_key()` décompose l'adresse en quadruplet
d'entiers, ce qui trie `192.168.0.9` avant `192.168.0.10`. Les entrées sans IP
(stations Wi-Fi sans bail) partent en fin de liste.

### 6. `is_disconnect_error()` remplace un test d'expression régulière

Le JS testait `/injoignable|timeout|socket|ECONNRESET/i` sur le message d'erreur
au moment du redémarrage. La fonction est nommée et partagée, mais la méthode
reste la même — et elle reste fragile : elle dépend du texte de l'erreur.

### 7. Décodage tolérant du corps HTTP

`_parse_response()` décode en `utf-8` avec `errors="replace"`. Le corps chiffré
mal découpé ne doit pas lever ici : c'est `_decrypt_body()` qui doit
diagnostiquer, avec un message compréhensible.

## Ce qui a été vérifié contre le JS

Comparaison directe entre les deux implémentations, sur les mêmes entrées :

| Couche | Vérification |
|---|---|
| RSA | 6 cas dont bloc vide, 64 et 65 octets, UTF-8 — **sorties identiques** |
| `build_payload` | 6 cas dont actions multiples et stacks — **chaînes identiques** |
| `parse_response` | 3 cas dont `$.ret` négatif et valeurs contenant `=` — **résultats identiques** |
| AES-128-CBC | chiffrés **identiques à Node**, et déchiffrement des chiffrés produits par Node |

Ces vérifications sont figées dans `tests/test_protocol.py` : les valeurs
attendues y sont celles produites par le JS, pas par le Python.

## Ce qui n'est PAS vérifié

Aucun test ne s'exécute contre un vrai routeur. Restent à confirmer sur
matériel :

- le parcours complet `fetch_params` → `login` → requête → `logout` ;
- la reprise de session après expiration (`SESSION_ERRORS`) ;
- le comportement de `reboot()`, qui repose sur une détection de déconnexion par
  message d'erreur ;
- le décodage `chunked` tolérant sur les pages d'erreur du firmware.
