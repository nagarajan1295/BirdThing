#!/usr/bin/env python3
"""Pairing window: scan classic Bluetooth for N minutes and pair+trust any
speaker that shows up in pairing mode (Audio/Video class or an A2DP sink).
After each pair it connects briefly, samples link RSSI, then disconnects so
the speaker is not held. Results -> /opt/party/speakers.json (merged)."""
import dbus, json, os, re, subprocess, sys, time

MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 20
OUT = "/opt/party/speakers.json"
A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"

bus = dbus.SystemBus()
om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
ad_path = "/org/bluez/hci0"
adapter = dbus.Interface(bus.get_object("org.bluez", ad_path), "org.bluez.Adapter1")

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def load():
    try:
        return json.load(open(OUT))
    except Exception:
        return {}

NAME_OK = re.compile(r"echo|alexa|google|nest|home|speaker", re.I)

def is_speaker(p):
    if not NAME_OK.search(str(p.get("Name", ""))):
        return False          # never pair a neighbour's random speaker
    cls = int(p.get("Class", 0))
    if cls and ((cls >> 8) & 0x1F) == 0x04:      # major class Audio/Video
        return True
    return A2DP_SINK in [str(u) for u in p.get("UUIDs", [])]

def rssi(mac):
    vals = []
    for _ in range(6):
        r = subprocess.run(["hcitool", "rssi", mac], capture_output=True, text=True)
        if "RSSI return value" in r.stdout:
            vals.append(int(r.stdout.split(":")[-1]))   # dB relative to the golden range
        time.sleep(0.5)
    return vals

# Pairing must create a BOND (stored keys). A non-bondable adapter pairs, then
# forgets the key, and the speaker refuses every later connection.
ad_props = dbus.Interface(bus.get_object("org.bluez", ad_path), "org.freedesktop.DBus.Properties")
ad_props.Set("org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(0))
ad_props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
adapter.SetDiscoveryFilter({"Transport": dbus.String("bredr")})
adapter.StartDiscovery()
log(f"pairing window open for {MINUTES:g} min")
tried, retry_at = set(), {}
end = time.time() + MINUTES * 60
try:
    while time.time() < end:
        for path, ifs in om.GetManagedObjects().items():
            p = ifs.get("org.bluez.Device1")
            if not p or not path.startswith(ad_path) or path in tried:
                continue
            if p.get("Paired") or not is_speaker(p) or time.time() < retry_at.get(path, 0):
                continue
            mac, name = str(p["Address"]), str(p.get("Name", p.get("Alias", "?")))
            tried.add(path)
            log(f"found speaker {name} {mac} adv-rssi={p.get('RSSI')}; pairing")
            dev = bus.get_object("org.bluez", path)
            props = dbus.Interface(dev, "org.freedesktop.DBus.Properties")
            try:
                dbus.Interface(dev, "org.bluez.Device1").Pair(timeout=60)
                props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
                log(f"  paired {name}")
                dbus.Interface(dev, "org.bluez.Device1").Connect(timeout=30)
                time.sleep(3)
                samples = rssi(mac)
                log(f"  link rssi samples {samples}")
                dbus.Interface(dev, "org.bluez.Device1").Disconnect()
            except dbus.DBusException as e:
                log(f"  failed: {e.get_dbus_name()} {e.get_dbus_message()}")
                samples = None
                tried.discard(path)       # keep retrying while it is in pairing mode
                retry_at[path] = time.time() + 20
            data = load()
            data[mac] = dict(data.get(mac, {}), name=name, adv_rssi=int(p.get("RSSI", 0) or 0),
                             link_rssi=samples, paired_at=time.strftime("%Y-%m-%d %H:%M"))
            json.dump(data, open(OUT, "w"), indent=1)
        time.sleep(2)
finally:
    try:
        adapter.StopDiscovery()
    except dbus.DBusException:
        pass
    log("pairing window closed")
