# TP-Link Legacy — Home Assistant integration

[!["Buy Me A Coffee"](https://raw.githubusercontent.com/Smeagolworms4/donate-assets/master/coffee.png)](https://www.buymeacoffee.com/smeagolworms4)
[!["Buy Me A Coffee"](https://raw.githubusercontent.com/Smeagolworms4/donate-assets/master/paypal.png)](https://www.paypal.com/donate/?business=SURRPGEXF4YVU&no_recurring=0&item_name=Hello%2C+I%27m+SmeagolWorms4.+For+my+open+source+projects.%0AThanks+you+very+mutch+%21%21%21&currency_code=EUR)

*Read this in [French](README.fr.md).*

Home Assistant integration for **legacy TP-Link routers** — the firmwares that
expose `/cgi_gdpr`, including the **TL-WR841N v13/v14**, which the official
TP-Link integration has never covered.

It speaks the router's web-interface protocol directly: no browser, no cloud, no
external dependency.

![hacs](https://img.shields.io/badge/HACS-custom%20repository-41BDF5)
![iot class](https://img.shields.io/badge/IoT%20class-local%20polling-6ee7a8)
![license](https://img.shields.io/badge/license-MIT-blue)

## ⚠️ Home Assistant must sit on the router's LAN

These firmwares enforce a "GDPR" restriction: objects holding personal data —
Wi-Fi passphrase, client MAC addresses, WAN credentials — are only readable by a
client **on the same local network**. From another subnet the router answers
`HTTP 500` for those objects and exposes only model, firmware and mode.

The router says so itself through `/cgi/info`:

```
userType="Admin"  clientLocal=1   → everything is readable
userType="Admin"  clientLocal=0   → only non-personal data is
```

This comes from the router, not from this integration: the JavaScript of its own
web interface receives the very same `HTTP 500` in that situation. The
integration detects it and explains it in the logs instead of creating empty
entities.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ menu → *Custom repositories*
2. URL `https://github.com/GollumDom/tp-link-legacy-integration`, category *Integration*
3. Install **TP-Link Legacy**, then restart Home Assistant

### Manual

Copy `custom_components/tplink_legacy` into your configuration's
`custom_components` folder, then restart Home Assistant.

### Setup

*Settings → Devices & services → Add integration → TP-Link Legacy*, then enter
the router's IP address and web-interface password (the user is `admin` by
default).

A router accepts **only one administrator at a time**: if you are logged into its
web interface in a browser, the integration may be locked out, and vice versa.

## Entities

| Entity | Type | Detail |
|---|---|---|
| Connected devices | sensor | client count (DHCP leases + Wi-Fi stations) |
| Up since | sensor | timestamp, derived from uptime |
| Public / Local IP address | sensor | diagnostic |
| WAN status | sensor | diagnostic |
| Internet | binary sensor | WAN connectivity |
| Wi-Fi *band* | switch | turns a radio on/off; SSID, channel and security as attributes |
| Reboot | button | reboots the router |
| *per device* | device_tracker | presence, IP, hostname, wired or Wi-Fi |

`device_tracker` entities are created as devices are discovered; a device seen
once becomes *away* instead of disappearing.

Polled every 30 s. The router's httpd is slow (~25 ms per request, one at a
time), so the integration keeps a single session per router.

## The client on its own

`custom_components/tplink_legacy/api` is a standalone asyncio client, usable
outside Home Assistant:

```python
from tplink_legacy.api import TpLinkRouter

router = TpLinkRouter(host="192.168.0.1", password="…")
try:
    print(await router.get_status())
    await router.set_wireless_enabled(False, band="2.4GHz")
finally:
    await router.disconnect()   # frees the administrator slot
```

A JavaScript counterpart exists, with a REST server and a command line: see
[`docs/PORTAGE.md`](docs/PORTAGE.md) and the npm package
[tp-link-legacy-api](https://github.com/Smeagolworms4/tp-link-legacy-api).

## Protocol

Reverse-engineered from the `js/lib.js` and `js/tpEncrypt.js` scripts served by
the router — details in [`docs/API.md`](docs/API.md).

1. `POST /cgi?8` → 512-bit RSA public key (`nn`, `ee`) and session counter (`seq`).
2. The client draws an AES-128-CBC key and IV (16 digits each).
3. Every request goes to `POST /cgi_gdpr`, body
   `sign=<RSA hex>\r\ndata=<AES base64>\r\n`.
4. The response is AES base64.

Two traps for anyone reimplementing this:

- **`Referer` is mandatory** — without it the router answers `403` on everything,
  including its own `.js` files.
- **The signature must replay `key=…&iv=…` on every request.** The short form
  (`h=…&s=…`) the firmware offers assumes the router still holds the session key
  in memory; once that context is lost it yields a `500` and voids the cookie.

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests cover the protocol and the high-level API, with no router involved.

## License

MIT
