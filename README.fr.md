# TP-Link Legacy — intégration Home Assistant

[!["Buy Me A Coffee"](https://raw.githubusercontent.com/Smeagolworms4/donate-assets/master/coffee.png)](https://www.buymeacoffee.com/smeagolworms4)
[!["Buy Me A Coffee"](https://raw.githubusercontent.com/Smeagolworms4/donate-assets/master/paypal.png)](https://www.paypal.com/donate/?business=SURRPGEXF4YVU&no_recurring=0&item_name=Hello%2C+I%27m+SmeagolWorms4.+For+my+open+source+projects.%0AThanks+you+very+mutch+%21%21%21&currency_code=EUR)

*Lire ceci en [anglais](README.md).*

Intégration pour les routeurs TP-Link « legacy » — les firmwares qui exposent
`/cgi_gdpr`, dont le **TL-WR841N v13/v14**, jamais couverts par l'intégration
TP-Link officielle.

Elle parle directement le protocole de l'interface web du routeur : ni
navigateur, ni cloud, ni dépendance externe.

## ⚠️ Home Assistant doit être sur le LAN du routeur

Ces firmwares appliquent une restriction « GDPR » : les objets contenant des
données personnelles — clé Wi-Fi, adresses MAC des clients, identifiants WAN —
ne sont lisibles que par un client **du même réseau local**. Depuis un autre
sous-réseau, le routeur répond `HTTP 500` sur ces objets et n'expose que le
modèle, le firmware et le mode.

Le routeur le dit lui-même via `/cgi/info` :

```
userType="Admin"  clientLocal=1   → tout est lisible
userType="Admin"  clientLocal=0   → seules les données non personnelles le sont
```

Ce comportement vient du routeur : le JavaScript de sa propre interface web
reçoit le même `HTTP 500` dans cette situation. L'intégration le détecte et le
signale dans les journaux plutôt que de créer des entités vides.

## Installation

### Prérequis : HACS

HACS (Home Assistant Community Store) est ce qui installe et met à jour les
intégrations non livrées avec Home Assistant. Si vous ne l'avez pas encore :

1. Suivez le guide officiel : **<https://hacs.xyz/docs/use/download/download/>**
   (il détaille le script de téléchargement, puis le redémarrage de Home Assistant)
2. Ajoutez HACS comme intégration :
   *Paramètres → Appareils et services → Ajouter une intégration → HACS*
3. Il demande d'autoriser un compte GitHub — HACS lit les dépôts via l'API GitHub

Une fois HACS présent dans votre barre latérale, revenez ici.

*Vous n'utilisez pas HACS ? Passez à [l'installation manuelle](#manuelle)
ci-dessous, elle ne demande aucun outil supplémentaire.*

### HACS — en un clic

[![Ouvrir votre instance Home Assistant et afficher ce dépôt dans le Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=GollumDom&repository=tp-link-legacy-integration&category=integration)

Le bouton ouvre directement le dépôt dans HACS sur votre instance. Installez
**TP-Link Legacy**, puis redémarrez Home Assistant.

<details>
<summary>Étapes manuelles dans HACS</summary>

1. HACS → Intégrations → menu ⋮ → *Dépôts personnalisés*
2. URL : `https://github.com/GollumDom/tp-link-legacy-integration`, catégorie *Intégration*
3. Installer **TP-Link Legacy**, puis redémarrer Home Assistant

</details>

### Manuelle

Copier `custom_components/tplink_legacy` dans le dossier `custom_components` de
votre configuration, puis redémarrer Home Assistant.

### Configuration

[![Ouvrir votre instance Home Assistant et commencer la configuration d'une nouvelle intégration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tplink_legacy)

Ou *Paramètres → Appareils et services → Ajouter une intégration → TP-Link
Legacy*. Saisissez l'adresse IP et le mot de passe de l'interface web du routeur
(l'utilisateur est `admin` par défaut).

Un routeur n'accepte **qu'un administrateur connecté à la fois** : si vous êtes
connecté à son interface web dans un navigateur, l'intégration peut en être
écartée, et inversement.

## Entités

| Entité | Type | Détail |
|---|---|---|
| Appareils connectés | capteur | nombre de clients (baux DHCP + stations Wi-Fi) |
| Démarré le | capteur | horodatage, à partir de l'*uptime* |
| Adresse IP publique / locale | capteur | diagnostic |
| État WAN | capteur | diagnostic |
| Internet | capteur binaire | connectivité WAN |
| Wi-Fi *bande* | interrupteur | allume/éteint une radio ; SSID, canal et sécurité en attributs |
| Redémarrer | bouton | redémarre le routeur |
| *par appareil* | device_tracker | présence, IP, nom d'hôte, filaire ou Wi-Fi |

Les `device_tracker` sont créés au fur et à mesure de la découverte des
appareils ; un appareil déjà vu passe *absent* au lieu de disparaître.

Interrogation toutes les 30 s. Le httpd du routeur est lent (~25 ms par requête,
une seule à la fois) : l'intégration n'ouvre qu'une session par routeur.

## Le client seul

`custom_components/tplink_legacy/api` est un client asyncio autonome, utilisable
hors Home Assistant :

```python
from tplink_legacy.api import TpLinkRouter

router = TpLinkRouter(host="192.168.0.1", password="…")
try:
    print(await router.get_status())
    await router.set_wireless_enabled(False, band="2.4GHz")
finally:
    await router.disconnect()   # libère le slot administrateur
```

Un équivalent JavaScript existe, avec serveur REST et ligne de commande :
voir [`docs/PORTAGE.md`](docs/PORTAGE.md) et le paquet npm
[tp-link-legacy-api](https://github.com/Smeagolworms4/tp-link-legacy-api).

## Protocole

Relevé dans les scripts `js/lib.js` et `js/tpEncrypt.js` servis par le routeur —
détail dans [`docs/API.md`](docs/API.md).

1. `POST /cgi?8` → clé publique RSA 512 bits (`nn`, `ee`) et compteur (`seq`).
2. Le client tire une clé AES-128-CBC et un IV (16 chiffres chacun).
3. Chaque requête part en `POST /cgi_gdpr`, corps
   `sign=<hexa RSA>\r\ndata=<base64 AES>\r\n`.
4. La réponse est du base64 AES.

Deux pièges pour qui réimplémente :

- **`Referer` est obligatoire** — sans lui, le routeur répond `403` sur tout.
- **La signature doit rejouer `key=…&iv=…` à chaque requête.** La forme courte
  (`h=…&s=…`) que propose le firmware suppose que le routeur a encore la clé de
  session en mémoire ; sinon elle produit un `500` et invalide le cookie.

## Tests

```bash
python3 -m unittest discover -s tests
```

Les tests couvrent le protocole et l'API haut niveau, sans routeur.

## Licence

MIT
