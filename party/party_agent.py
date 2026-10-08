#!/usr/bin/env python3
"""House Party agent (runs as root on the bedroom Pi).

Watches the snapserver AirPlay stream. While it is playing, it connects every
enabled speaker in /opt/party/speakers.json over Bluetooth and starts one
snapclient per speaker (into that speaker's BlueALSA PCM).
After IDLE_S of silence it stops the clients and drops the Bluetooth links, so
the Echoes are free again for the phone / follow-me audio when no party is on.
"""
import dbus, json, os, subprocess, time, urllib.request

CONF = "/opt/party/speakers.json"
RPC = "http://192.168.1.250:1780/jsonrpc"  # snapserver + AirPlay live on the living-room Pi
IDLE_S = 120
# roomloc's continuous BLE discovery hogs the Pi's shared WiFi/BT radio; with
# two A2DP streams on top, WiFi starves (snapclient TCP drops). Pause it while
# a party plays - follow-me audio can't use the Echoes then anyway.
PAUSE_UNITS = ["roomloc-node.service"]
RETRY_S = 20
LOG = "/var/log/party-agent.log"

bus = dbus.SystemBus()
om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")


def log(msg):
    with open(LOG, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def rpc(method, params=None):
    body = json.dumps({"id": 1, "jsonrpc": "2.0", "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(RPC, body, {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=8))["result"]


def playing():
    try:
        return any(s["status"] == "playing" for s in rpc("Server.GetStatus")["server"]["streams"])
    except Exception:
        return False


def speakers():
    try:
        return {m: s for m, s in json.load(open(CONF)).items() if s.get("enabled", True)}
    except Exception:
        return {}


def dev(mac):
    return bus.get_object("org.bluez", "/org/bluez/hci0/dev_" + mac.replace(":", "_"))


def connected(mac):
    try:
        props = dbus.Interface(dev(mac), "org.freedesktop.DBus.Properties")
        return bool(props.Get("org.bluez.Device1", "Connected"))
    except dbus.DBusException:
        return False


def pcm_ready(mac):
    """BlueALSA has an A2DP playback PCM for this speaker (i.e. the link is up as Pi->speaker)."""
    try:
        mgr = dbus.Interface(bus.get_object("org.bluealsa", "/org/bluealsa"), "org.bluealsa.Manager1")
        tag = "dev_" + mac.replace(":", "_") + "/a2dpsrc"
        return any(tag in str(path) for path in mgr.GetPCMs())
    except dbus.DBusException:
        return False


def unit(mac):
    return "party-client@" + mac.replace(":", "") + ".service"


def systemctl(*args):
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=15)


def client_active(mac):
    return systemctl("is-active", unit(mac)).stdout.strip() == "active"


def main():
    last_play, ours, next_try, paused = 0.0, set(), {}, False
    log("agent start")
    for u in PAUSE_UNITS:          # never leave them stopped across an agent restart
        systemctl("start", u)
    while True:
        spk = speakers()
        if playing():
            last_play = time.time()
            if not paused:
                for u in PAUSE_UNITS:
                    systemctl("stop", u)
                paused = True
                log("paused " + ", ".join(PAUSE_UNITS))
            for mac, s in spk.items():
                if not connected(mac):
                    if time.time() >= next_try.get(mac, 0):
                        next_try[mac] = time.time() + RETRY_S
                        try:
                            dbus.Interface(dev(mac), "org.bluez.Device1").Connect(timeout=25)
                            ours.add(mac)
                            log(f"connected {s.get('name', mac)}")
                        except dbus.DBusException as e:
                            log(f"connect {s.get('name', mac)} failed: {e.get_dbus_message()}")
                    continue
                if not client_active(mac) and pcm_ready(mac):
                    systemctl("start", unit(mac))
                    log(f"client up {s.get('name', mac)}")
        elif last_play and time.time() - last_play > IDLE_S:
            for mac in list(spk) + list(ours):
                systemctl("stop", unit(mac))
            for mac in ours:
                try:
                    dbus.Interface(dev(mac), "org.bluez.Device1").Disconnect()
                except dbus.DBusException:
                    pass
            for u in PAUSE_UNITS:
                systemctl("start", u)
            paused = False
            log(f"idle {IDLE_S}s: released {len(ours)} speaker(s), resumed " + ", ".join(PAUSE_UNITS))
            ours.clear()
            last_play = 0.0
        time.sleep(2)


if __name__ == "__main__":
    main()
