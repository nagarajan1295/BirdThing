# ANCS — iPhone notifications on the house displays

Puts iPhone notifications — **including incoming calls and message
previews** — on the BirdThing dashboard, the WeatherThing Car Thing and the
bedroom weather kiosk. No app, no cloud, no extra hardware.

## How it works

Apple publishes **ANCS** (Apple Notification Center Service), the BLE service
fitness bands use. The BirdThing Pi advertises itself as a BLE peripheral
*soliciting* ANCS; once the iPhone pairs and grants notification access, the
Pi becomes a GATT client against the phone and receives every notification
the phone shows: app id, title (the caller/sender), the message body, and a
distinct `IncomingCall` category.

```
iPhone --BLE/ANCS--> BirdThing Pi (gateway :8099) --HTTP--> the three displays
```

One radio serves all three screens: the gateway holds notifications in memory
and every display reads the same JSON.

## Why the BirdThing Pi

Its Bluetooth adapter was idle — Bluetooth had been disabled on this Pi so
nothing would claim `DC:A6:32:62:53:01`, the address the **bedroom Pi spoofs**
to serve the WeatherThing over BT PAN. That address collision is the one real
hazard in reusing this radio, so the adapter is forced **LE-only** via
`ControllerMode = le` in `/etc/bluetooth/main.conf`. With classic Bluetooth
off it can never answer the Car Thing's paging or appear in its inquiry.
ANCS needs only BLE, so nothing is lost.

The bedroom Pi's adapter is deliberately **not** touched — it is a
serdev-attached BCM4345C0 with a long history of wedging, and the WeatherThing
depends on it.

## Files

| file | what it is |
| --- | --- |
| `ancs_gateway.py` | the gateway: BlueZ D-Bus advertising + agent, ANCS GATT client, JSON API on `:8099` |
| `ancs-prep.sh` | clears the leftover rfkill soft-block, waits for `hci0` |
| `ancs-prep.service` / `ancs-gateway.service` | systemd units (both enabled) |
| `notify_widget.html` | the toast — self-contained CSS+JS, injected into each display |
| `patch_display.py` | idempotently injects the toast into a display's HTML |
| `patch_api_route.py` | idempotently adds a same-origin `/api/notify` proxy to a Pi's API server |

## Deploy

```bash
sudo mkdir -p /opt/ancs && sudo cp ancs_gateway.py ancs-prep.sh /opt/ancs/
sudo cp ancs-prep.service ancs-gateway.service /etc/systemd/system/
sudo sed -i 's|^#ControllerMode = dual|ControllerMode = le|' /etc/bluetooth/main.conf
sudo systemctl daemon-reload
sudo systemctl enable --now bluetooth ancs-prep ancs-gateway
```

Needs `python3-dbus` and `python3-gi`.

## Pairing

iPhone → Settings → Bluetooth → **BirdThing** → pair, then allow
*Show Notifications* (or enable it under the ⓘ). BLE range is ~10 m, so the
phone only feeds the gateway while it is near this Pi.

## The displays

Each display polls a URL every 2.5 s. The two Car Things have no route to the
gateway's host — the BirdThing CT reaches only its own Pi over USB, the
WeatherThing CT only its Pi over the BT PAN link — so each Pi's existing API
server proxies the gateway on the origin the page was loaded from.

| display | endpoint |
| --- | --- |
| BirdThing dashboard (birdpi `:8090`) | `/api/notify` → `127.0.0.1:8099` |
| WeatherThing (bedroom Pi `:8090`) | `/api/notify` → `192.168.1.250:8099` |
| bedroom kiosk (bedroom Pi `:8080`) | direct to `192.168.1.250:8099` (CORS) |

The first poll after a page load only seeds: a reload never replays the
backlog. Incoming calls stay on screen until the phone says the call ended;
everything else clears after 9 s. Notification text is rendered with
`textContent`, never `innerHTML`.

## API

- `GET /api/notifications` — recent notifications + `linked` state
- `GET /healthz`
- `GET /api/test?cat=IncomingCall&app=Phone&title=X&message=Y` — inject a
  synthetic notification to test the display chain without a real call
- `GET /api/test/clear`

## Config — `/etc/ancs-gateway.json` (optional)

```json
{"redact_body": false, "expire_sec": 240, "log_bodies": false}
```

Set `redact_body` to `true` to send sender only and never the message text —
worth considering, since these are always-on screens visible to anyone in the
room. Message bodies stay out of the journal unless `log_bodies` is set.

## Limits

- **Range.** BLE is ~10 m. Away from this Pi, nothing arrives.
- **Unencrypted on the LAN.** The gateway serves message text over plain HTTP
  to anything on the network.
- iOS re-grants ANCS on reconnect; if notifications stop, check
  *Show Notifications* is still on under the ⓘ next to BirdThing.
