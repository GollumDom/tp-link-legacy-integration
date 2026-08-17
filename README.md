# TP-Link Legacy — intégration Home Assistant

Intégration pour les routeurs TP-Link « legacy » — TL-WR841N v13/v14 et proches,
c'est-à-dire les firmwares qui exposent `/cgi_gdpr` et que l'intégration
officielle `tplink` de Home Assistant ne gère pas.

> **État : en construction.** Le client Python du routeur est écrit et testé ;
> l'intégration Home Assistant proprement dite (config flow, coordinator,
> entités) reste à faire. Voir [Feuille de route](#feuille-de-route).

## Ce qui fonctionne aujourd'hui

`custom_components/tplink_legacy/api/` — un client asynchrone complet :

```python
from tplink_legacy.api import TpLinkRouter

router = TpLinkRouter(host="192.168.0.1", password="motdepasse")
try:
    status = await router.get_status()
    print(status["info"]["model"], "—", status["clientCount"], "appareils")
    await router.set_wireless_enabled(False, band="5GHz")
finally:
    await router.disconnect()
```

Lecture : informations système, LAN, ports Ethernet, WAN, radios Wi-Fi, baux
DHCP, stations associées, et une vue unifiée des appareils connectés.
Écriture : allumage des radios, SSID, redémarrage.

📖 **[Documentation de l'API](docs/API.md)** — méthodes, structures rendues,
accès bas niveau par OID, erreurs.
📖 **[Notes de portage](docs/PORTAGE.md)** — correspondance avec le client
JavaScript d'origine et écarts assumés.

## Matériel visé

Testé sur **TL-WR841N v14** (firmware 0.9.1 4.17). Le protocole est commun à la
gamme : les modèles servant `/cgi_gdpr` et `js/tpEncrypt.js` devraient
fonctionner.

Si un OID manque sur votre modèle, la section concernée rend `null` sans faire
échouer le reste — `get_status()` isole chaque section.

## Contraintes du firmware, à connaître avant de commencer

Ce ne sont pas des limites de l'intégration mais du routeur lui-même, et elles
dictent la conception :

| Contrainte | Conséquence |
|---|---|
| **Un seul administrateur connecté à la fois** | Ouvrir l'interface web dans un navigateur déconnecte l'intégration, et inversement. |
| **Verrouillage 2 h après 10 échecs de mot de passe** | Un mot de passe erroné dans la configuration bloque l'accès pour 2 heures. |
| **Pas de requêtes concurrentes** | Les appels sont sérialisés par session. |
| **Réponses HTTP malformées** | Le routeur annonce `Transfer-Encoding: chunked` sans l'appliquer ; les clients HTTP stricts échouent, d'où un parseur maison. |

C'est la première contrainte qui justifie le futur interrupteur **Fetch data**
(voir ci-dessous) : pouvoir suspendre l'interrogation pour reprendre la main sur
l'interface web.

## Installation

### HACS

*(à venir — le dépôt n'est pas encore publiable en tant qu'intégration)*

### Manuelle

*(à venir)*

## Feuille de route

- [x] Client Python du routeur (`api/`) — 33 tests
- [x] Documentation de l'API et notes de portage
- [ ] `manifest.json`, `hacs.json`, `info.md` — publication HACS
- [ ] Config flow : hôte, identifiants, intervalle d'interrogation
- [ ] `DataUpdateCoordinator` sur `get_status()`
- [ ] Entités
  - [ ] `binary_sensor` — connexion WAN
  - [ ] `sensor` — uptime, IP publique, nombre d'appareils, débit du lien
  - [ ] `switch` — radios Wi-Fi
  - [ ] `switch` — **Fetch data** : suspend l'interrogation du routeur
  - [ ] `button` — redémarrage
  - [ ] `device_tracker` — présence des appareils
- [ ] Traductions FR / EN

## Développement

```bash
python3 -m unittest discover -s tests
```

Aucune dépendance de test. Le client n'a besoin que de `cryptography`, déjà
présent dans Home Assistant.

## Origine

Portage du client JavaScript `Works/JS/tplink`, lui-même issu de la
rétro-ingénierie des scripts servis par l'interface web du routeur
(`js/lib.js`, `js/tpEncrypt.js`, `js/encrypt.js`, `js/oid_str.js`, `js/err.js`).
