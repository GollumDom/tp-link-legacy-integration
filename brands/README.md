# Visuels de marque

Les fichiers servis à Home Assistant sont dans
[`../custom_components/tplink_legacy/brand/`](../custom_components/tplink_legacy/brand/) :
`icon.png` (256×256), `icon@2x.png` (512×512), `logo.png`, `logo@2x.png`.

Depuis **Home Assistant 2026.3**, une intégration personnalisée sert ses propres
visuels depuis ce dossier `brand/`, sans configuration ni champ de manifeste, et
ils priment sur le CDN `brands.home-assistant.io`. Le dépôt
`home-assistant/brands` n'accepte d'ailleurs plus les icônes d'intégrations
personnalisées — voir l'annonce
[Brands proxy API](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api).

Noms de fichiers reconnus : `icon.png`, `logo.png`, leurs variantes `@2x`, et les
versions sombres préfixées `dark_`.

`icon.svg` est la source. Pour régénérer les PNG :

```bash
inkscape brands/icon.svg -o custom_components/tplink_legacy/brand/icon@2x.png -w 512 -h 512
inkscape brands/icon.svg -o custom_components/tplink_legacy/brand/icon.png    -w 256 -h 256
cp custom_components/tplink_legacy/brand/icon.png    custom_components/tplink_legacy/brand/logo.png
cp custom_components/tplink_legacy/brand/icon@2x.png custom_components/tplink_legacy/brand/logo@2x.png
```
