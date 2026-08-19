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

## ⚠️ One administrator at a time

These firmwares accept a **single administrator session**. Every new login
invalidates the previous one — silently. Open the router's web interface while
Home Assistant is polling and the two evict each other every thirty seconds,
which shows up as entities that go blank at random.

Two things keep that under control:

- The whole snapshot is read in **one single request** instead of a dozen, so
  the window during which an eviction can land is as small as possible.
- A **Router polling** switch suspends the periodic reads. Turn it off before
  logging into the web interface; the integration releases its session
  immediately and stops polling until you turn it back on. The state survives a
  restart.

Nothing here depends on which subnet Home Assistant sits on — the router is
reachable and fully readable across a routed network.

## Installation

### Prerequisite: HACS

HACS (Home Assistant Community Store) is what installs and updates integrations
that are not shipped with Home Assistant. If you do not have it yet:

1. Follow the official guide: **<https://hacs.xyz/docs/use/download/download/>**
   (it walks through the download script, then restarting Home Assistant)
2. Add HACS itself as an integration:
   *Settings → Devices & services → Add integration → HACS*
3. It asks you to authorise a GitHub account — HACS reads the repositories
   through the GitHub API

Once HACS appears in your sidebar, come back here.

*Not using HACS? Jump to [Manual](#manual) below — it needs no extra tooling.*

### HACS — one click

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=GollumDom&repository=tp-link-legacy-integration&category=integration)

The button opens the repository straight inside HACS on your instance. Install
**TP-Link Legacy**, then restart Home Assistant.

<details>
<summary>Manual HACS steps</summary>

1. HACS → Integrations → ⋮ menu → *Custom repositories*
2. URL `https://github.com/GollumDom/tp-link-legacy-integration`, category *Integration*
3. Install **TP-Link Legacy**, then restart Home Assistant

</details>

### Manual

Copy `custom_components/tplink_legacy` into your configuration's
`custom_components` folder, then restart Home Assistant.

### Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tplink_legacy)

Or *Settings → Devices & services → Add integration → TP-Link Legacy*. Enter the
router's IP address and web-interface password (the user is `admin` by default).

A router accepts **only one administrator at a time**: if you are logged into its
web interface in a browser, the integration may be locked out, and vice versa.

### Automatic detection

These firmwares expose neither UPnP/SSDP nor mDNS — only port 80. The
integration therefore probes the plausible addresses (your Home Assistant
host's own gateway first, then the usual `192.168.x.1` / `10.0.x.1`) with a
request that needs no credentials: `POST /cgi?8` with `/cgi/getParm` returns the
session's RSA public key, which no other web server does. Routers found are
offered in a list; *Other address…* always leads to the manual form.

## Options

*Settings → Devices & services → TP-Link Legacy → Configure*

| Option | Default | Detail |
|---|---|---|
| Polling interval | 30 s | 10 to 600 s. The router's httpd is slow and handles one request at a time |
| Expose the Wi-Fi passphrase | off | adds the passphrase to the switch attributes; the firmware hands it over in clear |

If the router's password changes, Home Assistant offers a re-authentication form
instead of dropping the entry.

## About device trackers

`device_tracker` entities are created for every client the router reports, and
identified by MAC address. Like **every router integration shipped with Home
Assistant** (AsusWRT, Fritz!Box, UniFi, Netgear, Mikrotik…), they start
**disabled** unless Home Assistant already knows a device carrying that MAC —
this keeps installations with many clients from being flooded.

To use one that is disabled: *Settings → Devices & services → Entities*, search
the MAC address, then enable the entity.

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
| Router polling | switch | suspends the periodic reads, and releases the session |
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

## Icons and logo

Entity icons ship with the integration (`icons.json`) and need nothing else.

The **logo** shown by HACS and the integrations page is another matter: Home
Assistant serves it from the [home-assistant/brands](https://github.com/home-assistant/brands)
repository, so a custom integration cannot provide its own until a pull request
lands there. The artwork is ready in [`brands/`](brands/) — see
[`brands/README.md`](brands/README.md) for the submission.

<img src="brands/icon.png" alt="TP-Link Legacy icon" width="96" height="96">

## Tests

```bash
pip install -r requirements-test.txt
pytest
```

53 tests: the protocol and the high-level API without any router, plus the
integration itself loaded inside a real Home Assistant instance — config flow,
discovery, re-authentication, options, every entity, and the degraded case where
the router refuses personal data.

The protocol tests alone need no Home Assistant:

```bash
python3 -m unittest discover -s tests -p 'test_protocol.py'
```

## License

MIT
