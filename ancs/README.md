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
to serve the WeatherThing over BT PAN.

The bedroom Pi's adapter is deliberately **not** touched — it is a
serdev-attached BCM4345C0 with a long history of wedging, and the WeatherThing
depends on it.

## Dual mode is required (and the address clash that comes with it)

ANCS is pure BLE, so LE-only *ought* to work and would neatly dodge the
address clash. **It does not.** iOS will not list a pure-BLE peripheral in
Settings → Bluetooth however correct its solicitation is — verified on air:
AD type `0x15` carrying the real ANCS UUID, 100 ms interval, connectable,
named, and the iPhone showed nothing. Classic Bluetooth must be available for
the phone to discover and keep the accessory. Once connected, the ANCS link
itself rides LE (`hcitool con` shows `LE … AUTH ENCRYPT`).

So `ControllerMode = dual`, and the clash is **mitigated, not eliminated**:

- the Car Thing's stale bond was **removed** from this Pi, so it holds no link
  key and a Car Thing connection attempt cannot authenticate
- this Pi runs **no NAP service** (`birdthing-btnap` stays disabled)
- the gateway drops out of **inquiry scan while a phone is linked**

Do not re-enable `birdthing-btnap` or re-pair the Car Thing to this Pi.

### Two traps worth knowing

**`btmgmt` silently ignores its command when it has no tty** — it exits 0
having done nothing, and under systemd it blocks until the unit times out.
Every `btmgmt` call must go through a pty: `script -qec "btmgmt …" /dev/null`.

**Power-cycling `bredr` clears `ssp`.** Without Secure Simple Pairing the
adapter offers only legacy PIN pairing and iOS will not pair with it at all —
while still looking healthy in `hciconfig`. Always check that `current
settings` contains **both** `br/edr` and `ssp`. `ancs-prep.sh` asserts this on
every boot.

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
sudo sed -i 's|^#ControllerMode = dual|ControllerMode = dual|' /etc/bluetooth/main.conf
sudo sed -i 's|^#Experimental = false|Experimental = true|' /etc/bluetooth/main.conf
sudo systemctl daemon-reload
sudo systemctl enable --now bluetooth ancs-prep ancs-gateway
```

Needs `python3-dbus` and `python3-gi`. `Experimental = true` is what makes
BlueZ honour `SolicitUUIDs` and the advertising-interval properties — without
it BlueZ advertises every 1280 ms, slow enough that an iOS scan can take a
very long time to notice the Pi.

## Pairing

iPhone → Settings → Bluetooth → **BirdThing** under *Other Devices* → pair,
then allow *Show Notifications* (or enable it under the ⓘ). Range is ~10 m,
so the phone only feeds the gateway while it is near this Pi.

The Pi stays discoverable whenever **no phone is linked**, so you can always
re-pair from the phone alone. To force a window anyway:

```bash
curl "http://192.168.1.250:8099/api/pair?mins=20"
```

**If you tap "Forget This Device" on the phone, clear the Pi's side too** —
otherwise the bond is one-sided and pairing walls up in a
`LinkKeyRequest → NegativeReply → disconnect` loop (the same failure that cost
days on the Car Thing):

```bash
sudo bluetoothctl remove <phone-mac>
```

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
- `GET /api/pair?mins=20` — re-open classic discoverability to (re-)pair a phone
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
- **The address clash is mitigated, not gone** — see above. Classic Bluetooth
  has to stay enabled, so this Pi does answer paging on the address the bedroom
  Pi spoofs.
- iOS drops the link when idle. The gateway pages bonded phones every 30 s to
  bring it back; `br-connection-profile-unavailable` in the log is a harmless
  outbound attempt, the phone reconnects on its own terms.
- iOS re-grants ANCS on reconnect; if notifications stop, check
  *Show Notifications* is still on under the ⓘ next to BirdThing.
