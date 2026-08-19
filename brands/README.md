# Brand assets

Home Assistant and HACS only display a logo when the integration's domain exists
in the [home-assistant/brands](https://github.com/home-assistant/brands)
repository. Until then, `tplink_legacy` shows the default placeholder icon —
that is a rule of the Home Assistant project, not something an integration can
set for itself.

These files are ready for that submission. Open a pull request on
`home-assistant/brands` adding:

```
custom_integrations/tplink_legacy/icon.png       256×256
custom_integrations/tplink_legacy/icon@2x.png    512×512
custom_integrations/tplink_legacy/logo.png       256×256
custom_integrations/tplink_legacy/logo@2x.png    512×512
```

`icon.svg` is the source. Regenerate the PNGs with:

```bash
inkscape brands/icon.svg -o brands/icon@2x.png -w 512 -h 512
inkscape brands/icon.svg -o brands/icon.png    -w 256 -h 256
cp brands/icon.png brands/logo.png
cp brands/icon@2x.png brands/logo@2x.png
```

Entity icons need no such step: they ship in
`custom_components/tplink_legacy/icons.json` and work as soon as the integration
is installed.
