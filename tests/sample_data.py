"""Instantané représentatif d'un TL-WR841N v14, partagé par les tests."""

from __future__ import annotations

#: Instantané représentatif d'un TL-WR841N v14 renvoyé par ``get_status()``.
STATUS = {
    "host": "192.168.11.1",
    "name": "192.168.11.1",
    "info": {
        "host": "192.168.11.1",
        "model": "TL-WR841N",
        "description": "TP-Link Wireless N Router WR841N",
        "firmware": "0.9.1 4.17 v0001.0 Build 200903 Rel.58674n",
        "hardware": "TL-WR841N v14 00000014",
        "uptime": 76535,
        "mac": "48:22:54:2B:A2:D0",
        "mode": "Router",
    },
    "lan": {
        "ip": "192.168.11.1",
        "netmask": "255.255.255.0",
        "mac": "48:22:54:2B:A2:D0",
        "dhcpEnabled": True,
    },
    "wan": {
        "connected": True,
        "status": "Connected",
        "protocol": "IPoE",
        "ip": "88.120.10.5",
        "gateway": "88.120.10.1",
        "dns": ["1.1.1.1"],
        "uptime": 1234,
        "link": {"up": True, "speed": "100", "duplex": "Full"},
    },
    "wireless": [
        {
            "stack": "1,1,0,0,0,0",
            "band": "2.4GHz",
            "enabled": True,
            "ssid": "MAISONDOMO_1",
            "bssid": "48:22:54:2B:A2:D0",
            "channel": 13,
            "bandwidth": "20M",
            "hidden": False,
            "security": {"mode": "WPA2-PSK"},
            "present": True,
        },
        {
            "stack": "1,2,0,0,0,0",
            "band": "5GHz",
            "enabled": False,
            "ssid": "TP-Link_A2D0_5G",
            "bssid": "48:22:54:2B:A2:CF",
            "channel": 40,
            "bandwidth": "40M",
            "hidden": False,
            "security": {"mode": "WPA2-PSK"},
            "present": False,
        },
    ],
    "clients": [
        {
            "mac": "44:17:93:A4:D3:EC",
            "ip": "192.168.11.9",
            "hostname": "salon-tv",
            "connection": "wireless",
        },
        {
            "mac": "20:6E:F1:03:B0:70",
            "ip": "192.168.11.13",
            "hostname": None,
            "connection": "wired",
        },
    ],
    "clientCount": 2,
}
