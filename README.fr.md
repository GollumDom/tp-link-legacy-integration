# TP-Link Legacy — intégration Home Assistant

[!["Buy Me A Coffee"](https://raw.githubusercontent.com/Smeagolworms4/donate-assets/master/coffee.png)](https://www.buymeacoffee.com/smeagolworms4)
[!["Buy Me A Coffee"](https://raw.githubusercontent.com/Smeagolworms4/donate-assets/master/paypal.png)](https://www.paypal.com/donate/?business=SURRPGEXF4YVU&no_recurring=0&item_name=Hello%2C+I%27m+SmeagolWorms4.+For+my+open+source+projects.%0AThanks+you+very+mutch+%21%21%21&currency_code=EUR)

*Lire ceci en [anglais](README.md).*

Intégration pour les routeurs TP-Link « legacy » — les firmwares qui exposent
`/cgi_gdpr`, dont le **TL-WR841N v13/v14**, jamais couverts par l'intégration
TP-Link officielle.

Elle parle directement le protocole de l'interface web du routeur : ni
navigateur, ni cloud, ni dépendance externe.

## ⚠️ Un seul administrateur à la fois

Ces firmwares n'acceptent qu'**une seule session administrateur**. Toute nouvelle
connexion invalide la précédente, sans prévenir. Ouvrez l'interface web du
routeur pendant que Home Assistant l'interroge et les deux s'évincent toutes les
trente secondes — ce qui se voit sous forme d'entités qui se vident au hasard.

Deux mécanismes limitent la casse :

- L'instantané complet est lu en **une seule requête** au lieu d'une douzaine,
  ce qui réduit au minimum la fenêtre pendant laquelle une éviction peut tomber.
- Un interrupteur **Interrogation du routeur** suspend les relevés. Coupez-le
  avant d'ouvrir l'interface web : l'intégration rend sa session immédiatement
  et cesse d'interroger jusqu'à ce que vous le rallumiez. L'état survit à un
  redémarrage.

Rien de tout cela ne dépend du sous-réseau sur lequel se trouve Home Assistant :
le routeur est joignable et entièrement lisible à travers un réseau routé.

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

### Détection automatique

Ces firmwares n'exposent ni UPnP/SSDP ni mDNS — seul le port 80 est ouvert.
L'intégration sonde donc les adresses plausibles (d'abord la passerelle de
l'hôte Home Assistant, puis les `192.168.x.1` / `10.0.x.1` usuelles) avec une
requête qui ne demande aucun identifiant : `POST /cgi?8` avec `/cgi/getParm`
renvoie la clé publique RSA de session, ce qu'aucun autre serveur web ne fait.
Les routeurs trouvés sont proposés dans une liste ; *Autre adresse…* mène
toujours au formulaire manuel.

## Options

*Paramètres → Appareils et services → TP-Link Legacy → Configurer*

| Option | Défaut | Détail |
|---|---|---|
| Intervalle d'interrogation | 30 s | de 10 à 600 s. Le httpd du routeur est lent et ne traite qu'une requête à la fois |
| Exposer la clé Wi-Fi | désactivé | ajoute la clé aux attributs de l'interrupteur ; le firmware la livre en clair |

Si le mot de passe du routeur change, Home Assistant propose un formulaire de
ré-authentification au lieu d'abandonner l'entrée.

## À propos des device_tracker

Une entité `device_tracker` est créée pour chaque client vu par le routeur,
identifiée par son adresse MAC. Comme **toutes les intégrations routeur livrées
avec Home Assistant** (AsusWRT, Fritz!Box, UniFi, Netgear, Mikrotik…), elles
sont **désactivées** tant que Home Assistant ne connaît pas déjà un appareil
portant cette adresse MAC — cela évite de noyer les installations comptant
beaucoup de clients.

Pour en activer une : *Paramètres → Appareils et services → Entités*, cherchez
l'adresse MAC, puis activez l'entité.

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
| Interrogation du routeur | interrupteur | suspend les relevés et rend la session |
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

## Icônes et logo

Les icônes des entités sont livrées avec l'intégration (`icons.json`) et ne
demandent rien de plus.

Le **logo** affiché par HACS et la page des intégrations est un autre sujet :
Home Assistant le sert depuis le dépôt
[home-assistant/brands](https://github.com/home-assistant/brands), une
intégration tierce ne peut donc pas fournir le sien tant qu'une pull request n'y
a pas été acceptée. Les visuels sont prêts dans [`brands/`](brands/) — voir
[`brands/README.md`](brands/README.md) pour la soumission.

<img src="brands/icon.png" alt="Icône TP-Link Legacy" width="96" height="96">

## Tests

```bash
pip install -r requirements-test.txt
pytest
```

53 tests : le protocole et l'API haut niveau sans routeur, plus l'intégration
elle-même chargée dans une vraie instance Home Assistant — assistant de
configuration, détection, ré-authentification, options, chaque entité, et le cas
dégradé où le routeur refuse les données personnelles.

Les seuls tests de protocole se passent de Home Assistant :

```bash
python3 -m unittest discover -s tests -p 'test_protocol.py'
```

## Licence

MIT
