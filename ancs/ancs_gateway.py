#!/usr/bin/env python3
"""
ANCS gateway - Apple Notification Center Service consumer.

Runs on the Mac mini (Sentry host), whose Broadcom BT radio is stronger and
completely unused; it replaces the BirdThing Pi as the phone-facing end. The
host advertises itself as a BLE peripheral soliciting Apple's ANCS service.
Once the iPhone pairs and grants notification access, the host becomes a GATT
client against the phone's ANCS service and receives every notification the
phone shows - including incoming calls and messages, with sender and body.

Received notifications are held in memory and served as JSON on :8099 so the
BirdThing dashboard, the WeatherThing (via the bedroom Pi proxy) and the
bedroom kiosk can all render the same toast.

Stdlib + python3-dbus + python3-gi only. No internet, no cloud, no app.
"""

import json
import os
import struct
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

BUS_NAME = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADV_MGR_IFACE = "org.bluez.LEAdvertisingManager1"
AGENT_MGR_IFACE = "org.bluez.AgentManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

# --- ANCS UUIDs (Apple spec) ---------------------------------------------
ANCS_SVC = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"
NOTIFICATION_SOURCE = "9fbf120d-6301-42d9-8c58-25e699a21dbd"
CONTROL_POINT = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"
DATA_SOURCE = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"

ADV_PATH = "/org/birdthing/ancs/adv0"
AGENT_PATH = "/org/birdthing/ancs/agent"

# BlueZ runs one ATT operation at a time per connection, so a StartNotify
# issued while another is outstanding comes back InProgress. Retry that one
# characteristic after a short pause rather than restarting the whole attach.
SUBSCRIBE_RETRY_MS = 700
SUBSCRIBE_MAX_TRIES = 6
VERIFY_MAX_ROUNDS = 4

# --- ANCS constants -------------------------------------------------------
EVT_ADDED, EVT_MODIFIED, EVT_REMOVED = 0, 1, 2

FLAG_SILENT = 1 << 0
FLAG_IMPORTANT = 1 << 1
FLAG_PRE_EXISTING = 1 << 2
FLAG_POSITIVE_ACTION = 1 << 3
FLAG_NEGATIVE_ACTION = 1 << 4

CATEGORIES = {
    0: "Other", 1: "IncomingCall", 2: "MissedCall", 3: "Voicemail",
    4: "Social", 5: "Schedule", 6: "Email", 7: "News",
    8: "HealthAndFitness", 9: "BusinessAndFinance", 10: "Location",
    11: "Entertainment",
}

ATTR_APP_ID, ATTR_TITLE, ATTR_SUBTITLE, ATTR_MESSAGE = 0, 1, 2, 3
ATTR_MESSAGE_SIZE, ATTR_DATE = 4, 5

# order matters: the phone replies with attributes in the order requested
REQUESTED = [
    (ATTR_APP_ID, None),
    (ATTR_TITLE, 64),
    (ATTR_SUBTITLE, 64),
    (ATTR_MESSAGE, 256),
    (ATTR_DATE, None),
]

# friendly names for the bundle ids that actually matter here
APP_NAMES = {
    "com.apple.mobilephone": "Phone",
    "com.apple.mobilesms": "Messages",
    "com.apple.facetime": "FaceTime",
    "com.apple.mobilemail": "Mail",
    "com.apple.mobilecal": "Calendar",
    "com.apple.reminders": "Reminders",
    "com.apple.mobiletimer": "Clock",
    "net.whatsapp.whatsapp": "WhatsApp",
    "com.google.gmail": "Gmail",
    "com.burbn.instagram": "Instagram",
    "com.toyopagroup.picaboo": "Snapchat",
    "com.facebook.messenger": "Messenger",
    "ph.telegra.telegraph": "Telegram",
    "com.hammerandchisel.discord": "Discord",
    "com.microsoft.skype.teams": "Teams",
    "com.apple.shortcuts": "Shortcuts",
    "com.apple.Passbook": "Wallet",
    "com.ubercab.UberClient": "Uber",
}

CONFIG_PATH = "/etc/ancs-gateway.json"
DEFAULT_CONFIG = {
    "port": 8099,
    "adapter": "hci0",
    "local_name": "BirdThing Hub",
    "keep": 40,            # ring buffer size
    "expire_sec": 240,     # how long a notification stays "fresh" for toasts
    "redact_body": False,  # True = send sender only, never the message text
    "log_bodies": False,   # keep message text out of the journal by default
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        pass
    except Exception as exc:                                # noqa: BLE001
        log("config error, using defaults: %s" % exc)
    return cfg


CFG = load_config()


def log(msg):
    sys.stderr.write("[ancs] %s\n" % msg)
    sys.stderr.flush()


# --- shared state ---------------------------------------------------------
class Store:
    """Recent notifications, shared between the GLib loop and the HTTP thread."""

    def __init__(self, keep):
        self._lock = threading.Lock()
        self._items = deque(maxlen=keep)
        self._by_uid = {}
        self.linked = False        # phone connected and ANCS subscribed
        self.device = ""
        self.since = 0.0

    def add(self, item):
        with self._lock:
            old = self._by_uid.get(item["uid"])
            if old is not None:
                old.update(item)
                return old
            self._items.append(item)
            self._by_uid[item["uid"]] = item
            # deque eviction leaves stale uid keys behind; prune them
            live = {i["uid"] for i in self._items}
            for uid in [u for u in self._by_uid if u not in live]:
                self._by_uid.pop(uid, None)
            return item

    def remove(self, uid):
        with self._lock:
            item = self._by_uid.get(uid)
            if item:
                item["active"] = False
                item["removed_ts"] = time.time()

    def known(self, uid):
        with self._lock:
            return uid in self._by_uid

    def set_link(self, linked, device=""):
        with self._lock:
            self.linked = linked
            self.device = device
            self.since = time.time()
            if not linked:
                # ONLY calls get cancelled by a dropped link.
                #
                # This used to deactivate EVERY stored notification, and that
                # silently ate real notifications: the displays refuse to toast
                # anything with active=false and dismiss it if it is already up.
                # At the edge of BLE range the phone flaps every ~20s, so each
                # notification was killed within seconds of arriving - the
                # gateway logged the message correctly and no screen ever showed
                # it. 'active' means "the phone is still showing this", which is
                # driven by ANCS EVT_REMOVED; losing the radio link tells us
                # nothing about that, so it must not clear the flag.
                #
                # An incoming CALL is the exception: its banner is meant to stay
                # up until the phone says the call ended, so if the phone
                # vanishes mid-ring it would otherwise hang on screen forever.
                for item in self._items:
                    if item.get("call"):
                        item["active"] = False

    def snapshot(self, limit=20):
        now = time.time()
        with self._lock:
            items = [dict(i) for i in reversed(self._items)][:limit]
            linked, device, since = self.linked, self.device, self.since
        if CFG["redact_body"]:
            for i in items:
                i["message"] = ""
                i["redacted"] = True
        for i in items:
            i["age"] = round(now - i["ts"], 1)
            i["fresh"] = (now - i["ts"]) < CFG["expire_sec"]
        return {
            "ok": True,
            "now": now,
            "linked": linked,
            "device": device,
            "linked_since": since,
            "items": items,
        }


STORE = Store(CFG["keep"])

# set by main(); lets the HTTP thread re-open a pairing window
STATE = {"pair_until": 0.0, "set_discoverable": None}

# live diagnostics, surfaced by /api/status. "hit or miss" is impossible to
# debug from the outside without these, so they are cheap and always on.
DIAG = {
    "adapter": "",
    "address": "",
    "advertising": False,       # our ANCS solicitation is registered with bluez
    "adv_registered_at": 0.0,
    "adv_failures": 0,
    "adv_last_error": "",
    "bonded": [],               # [{path, alias, connected, services_resolved, rssi}]
    "last_reconnect_error": "",
    "last_reconnect_at": 0.0,
    "classic_connected": False, # phone attached over BR/EDR but no ANCS = the
                                # classic symptom of "connected but no toasts"
    # which ANCS characteristics are ACTUALLY subscribed. Without
    # notification_source nothing can ever arrive, however healthy the rest
    # of the link looks - this is the field to check first.
    "notifying": {"notification_source": False, "data_source": False},
    "started": time.time(),
}


# --- BlueZ helpers --------------------------------------------------------
def get_managed_objects(bus):
    om = dbus.Interface(bus.get_object(BUS_NAME, "/"), DBUS_OM_IFACE)
    return om.GetManagedObjects()


def find_adapter_path(bus, name):
    for path, ifaces in get_managed_objects(bus).items():
        if ADAPTER_IFACE in ifaces and path.endswith("/" + name):
            return path
    return None


class Advertisement(dbus.service.Object):
    """LE advertisement soliciting ANCS - this is what makes iOS offer the
    'Show Notifications' permission when the user pairs."""

    def __init__(self, bus, path, local_name):
        self.path = path
        self.local_name = local_name
        self.on_released = None      # set by main()'s advertising watchdog
        dbus.service.Object.__init__(self, bus, path)

    def get_properties(self):
        return {
            "org.bluez.LEAdvertisement1": {
                "Type": dbus.String("peripheral"),
                "SolicitUUIDs": dbus.Array([ANCS_SVC], signature="s"),
                "LocalName": dbus.String(self.local_name),
                "Includes": dbus.Array(["tx-power"], signature="s"),
                "Discoverable": dbus.Boolean(True),
                # BlueZ otherwise defaults to a 1280ms interval, which is slow
                # enough that iOS's Settings scan can take a very long time to
                # notice us. ~100-150ms is the usual pairing-friendly range.
                # Both properties need bluetoothd's Experimental mode.
                "MinInterval": dbus.UInt32(100),
                "MaxInterval": dbus.UInt32(150),
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != "org.bluez.LEAdvertisement1":
            raise dbus.exceptions.DBusException("org.bluez.Error.InvalidArguments")
        return self.get_properties()["org.bluez.LEAdvertisement1"]

    @dbus.service.method("org.bluez.LEAdvertisement1", in_signature="", out_signature="")
    def Release(self):
        log("advertisement released by bluez")
        if self.on_released:
            self.on_released()


class Agent(dbus.service.Object):
    """NoInputNoOutput agent - accepts the iPhone's Just Works pairing."""

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        log("authorized service %s for %s" % (uuid, device))

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        log("passkey for %s: %06u" % (device, passkey))

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        log("pincode for %s: %s" % (device, pincode))

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        log("confirming pairing with %s (passkey %06u)" % (device, passkey))

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        log("authorizing %s" % device)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        log("pairing cancelled")


# --- the ANCS client ------------------------------------------------------
class AncsClient:
    def __init__(self, bus, adapter_path):
        self.bus = bus
        self.adapter_path = adapter_path
        self.device_path = None
        self.cp = None            # control point characteristic proxy
        self.ds_buf = bytearray()
        self.pending = deque()    # notification uids awaiting attributes
        self.inflight = None

    # -- connection lifecycle --
    def scan_existing(self):
        """Attach to an already-connected iPhone (e.g. after a restart)."""
        objects = get_managed_objects(self.bus)
        for path, ifaces in objects.items():
            dev = ifaces.get(DEVICE_IFACE)
            if not dev or not dev.get("Connected"):
                continue
            if not str(path).startswith(str(self.adapter_path)):
                continue
            if dev.get("ServicesResolved"):
                self.try_attach(path, objects)

    def try_attach(self, device_path, objects=None):
        if self.device_path == device_path and self.cp is not None:
            return
        objects = objects or get_managed_objects(self.bus)
        chrcs = {}
        for path, ifaces in objects.items():
            chrc = ifaces.get(GATT_CHRC_IFACE)
            if not chrc:
                continue
            if not str(path).startswith(str(device_path) + "/"):
                continue
            chrcs[str(chrc["UUID"]).lower()] = path

        if NOTIFICATION_SOURCE not in chrcs or DATA_SOURCE not in chrcs:
            return  # not an ANCS provider, or notification access not granted yet

        log("ANCS found on %s - subscribing" % device_path)
        self.device_path = device_path
        self.ds_buf = bytearray()
        self.pending.clear()
        self.inflight = None

        try:
            dev = dbus.Interface(
                self.bus.get_object(BUS_NAME, device_path), DBUS_PROP_IFACE)
            dev.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
        except Exception as exc:                            # noqa: BLE001
            log("could not mark trusted: %s" % exc)

        if CONTROL_POINT in chrcs:
            self.cp = dbus.Interface(
                self.bus.get_object(BUS_NAME, chrcs[CONTROL_POINT]),
                GATT_CHRC_IFACE)
        else:
            self.cp = None
            log("no control point - titles/bodies will be unavailable")

        # Subscribe to both characteristics, SERIALLY - see _subscribe_chain.
        # Attaching does not wait for it: an earlier version refused to attach
        # until both subscribes returned cleanly, and that turned a transient
        # error into a total outage (the gateway gave up entirely and no
        # notification could arrive at all). The chain self-heals in the
        # background and reports the truth via /api/status.
        self._subscribe_chain(chrcs)

        name = "phone"
        try:
            props = dbus.Interface(
                self.bus.get_object(BUS_NAME, device_path), DBUS_PROP_IFACE)
            name = str(props.Get(DEVICE_IFACE, "Alias"))
        except Exception:                                   # noqa: BLE001
            pass
        STORE.set_link(True, name)
        log("linked to %s" % name)

    def _notifying(self, path):
        """The authoritative answer to 'am I subscribed?' - the exception from
        StartNotify is not one, since InProgress can still land successfully."""
        try:
            return bool(dbus.Interface(
                self.bus.get_object(BUS_NAME, path), DBUS_PROP_IFACE
            ).Get(GATT_CHRC_IFACE, "Notifying"))
        except Exception:                                   # noqa: BLE001
            return False

    def _subscribe_chain(self, chrcs, order=None, tries=0, verify_round=0):
        """StartNotify on the ANCS characteristics ONE AT A TIME.

        THE BUG THIS FIXES: BlueZ processes one ATT operation at a time per
        connection. Firing StartNotify on Data Source and Notification Source
        back-to-back means the second reliably collides with the first and
        returns `org.bluez.Error.InProgress`. Retrying on a timer collides
        again - observed as 7 consecutive InProgress failures on both
        characteristics, after which the gateway stopped attaching entirely.

        So each StartNotify is issued only from the PREVIOUS one's reply
        handler, and InProgress is retried on that characteristic alone rather
        than restarting the whole attach. Success is judged by the `Notifying`
        property, never by the absence of an exception.
        """
        if order is None:
            # data source first: it must be listening before any control-point
            # request goes out, or the reply is missed
            order = [DATA_SOURCE, NOTIFICATION_SOURCE]
        if not order:
            GLib.timeout_add(
                1000,
                lambda: (self._verify_notifying(chrcs, verify_round), False)[1])
            return

        uuid, rest = order[0], order[1:]
        path = chrcs.get(uuid)
        if path is None or self._notifying(path):
            self._subscribe_chain(chrcs, rest, verify_round=verify_round)
            return

        def ok():
            self._subscribe_chain(chrcs, rest, verify_round=verify_round)

        def err(exc):
            s = str(exc)
            if "Already" in s:
                self._subscribe_chain(chrcs, rest, verify_round=verify_round)
            elif "InProgress" in s and tries < SUBSCRIBE_MAX_TRIES:
                # let the in-flight operation finish, then retry THIS one only
                GLib.timeout_add(
                    SUBSCRIBE_RETRY_MS,
                    lambda: (self._subscribe_chain(chrcs, order, tries + 1,
                                                   verify_round), False)[1])
            else:
                log("StartNotify failed for %s: %s" % (uuid, exc))
                self._subscribe_chain(chrcs, rest, verify_round=verify_round)

        try:
            dbus.Interface(self.bus.get_object(BUS_NAME, path),
                           GATT_CHRC_IFACE).StartNotify(
                               reply_handler=ok, error_handler=err)
        except Exception as exc:                            # noqa: BLE001
            log("StartNotify dispatch failed for %s: %s" % (uuid, exc))
            self._subscribe_chain(chrcs, rest, verify_round=verify_round)

    def _verify_notifying(self, chrcs, round_=0):
        """Report what actually ended up subscribed, and heal it if not."""
        ns = self._notifying(chrcs[NOTIFICATION_SOURCE])
        ds = self._notifying(chrcs[DATA_SOURCE])
        DIAG["notifying"] = {"notification_source": ns, "data_source": ds}
        if ns and ds:
            log("subscribed: notification source + data source")
            return
        # Notification Source is the one that delivers events at all; without
        # it the link is useless however healthy it looks.
        if round_ >= VERIFY_MAX_ROUNDS:
            log("STILL not subscribed after %d rounds "
                "(notification_source=%s data_source=%s) - the phone has to "
                "reconnect; see /api/status" % (round_, ns, ds))
            return
        log("not fully subscribed (notification_source=%s data_source=%s)"
            " - healing, round %d" % (ns, ds, round_ + 1))
        retry = [u for u, okd in ((DATA_SOURCE, ds), (NOTIFICATION_SOURCE, ns))
                 if not okd]
        GLib.timeout_add(
            2000,
            lambda: (self._subscribe_chain(chrcs, retry, verify_round=round_ + 1),
                     False)[1])

    def detach(self, device_path):
        if device_path != self.device_path:
            return
        log("phone disconnected")
        self.device_path = None
        self.cp = None
        self.ds_buf = bytearray()
        DIAG["notifying"] = {"notification_source": False, "data_source": False}
        STORE.set_link(False)

    # -- notification source --
    def on_notification_source(self, value):
        data = bytes(value)
        if len(data) < 8:
            return
        event_id, flags, category, _count = data[0], data[1], data[2], data[3]
        uid = struct.unpack("<I", data[4:8])[0]

        if event_id == EVT_REMOVED:
            STORE.remove(uid)
            return
        if flags & FLAG_PRE_EXISTING:
            return          # backlog from before we connected - don't toast it
        if event_id == EVT_MODIFIED and STORE.known(uid):
            return

        item = {
            "uid": uid,
            "catid": category,
            "cat": CATEGORIES.get(category, "Other"),
            "app": "",
            "appid": "",
            "title": "",
            "subtitle": "",
            "message": "",
            "ts": time.time(),
            "silent": bool(flags & FLAG_SILENT),
            "important": bool(flags & FLAG_IMPORTANT),
            "call": category == 1,
            "active": True,
            "complete": False,
        }
        STORE.add(item)
        self.request_attributes(uid)

    def request_attributes(self, uid):
        if self.cp is None:
            return
        self.pending.append(uid)
        self.pump()

    def pump(self):
        """One outstanding control-point request at a time, so data-source
        fragments can never interleave between notifications."""
        if self.inflight is not None or not self.pending or self.cp is None:
            return
        uid = self.pending.popleft()
        self.inflight = uid
        payload = bytearray([0x00])                 # CommandID: GetNotificationAttributes
        payload += struct.pack("<I", uid)
        for attr, maxlen in REQUESTED:
            payload.append(attr)
            if maxlen is not None:
                payload += struct.pack("<H", maxlen)
        try:
            self.cp.WriteValue(dbus.Array([dbus.Byte(b) for b in payload],
                                          signature="y"),
                               {"type": dbus.String("request")})
        except dbus.exceptions.DBusException as exc:
            log("control point write failed: %s" % exc)
            self.inflight = None
            GLib.timeout_add(500, self._retry)

    def _retry(self):
        self.pump()
        return False

    # -- data source --
    def on_data_source(self, value):
        self.ds_buf += bytes(value)
        while True:
            parsed = self._parse_one()
            if not parsed:
                return

    def _parse_one(self):
        buf = self.ds_buf
        if len(buf) < 5:
            return False
        if buf[0] != 0x00:
            # only GetNotificationAttributes responses are expected; resync
            log("unexpected data-source command 0x%02x, resyncing" % buf[0])
            self.ds_buf = bytearray()
            self.inflight = None
            self.pump()
            return False

        uid = struct.unpack("<I", buf[1:5])[0]
        pos = 5
        attrs = {}
        for _ in range(len(REQUESTED)):
            if pos + 3 > len(buf):
                return False                        # more fragments coming
            attr_id = buf[pos]
            length = struct.unpack("<H", buf[pos + 1:pos + 3])[0]
            pos += 3
            if pos + length > len(buf):
                return False
            attrs[attr_id] = buf[pos:pos + length].decode("utf-8", "replace")
            pos += length

        self.ds_buf = buf[pos:]
        self.inflight = None
        self._emit(uid, attrs)
        self.pump()
        return True

    def _emit(self, uid, attrs):
        appid = attrs.get(ATTR_APP_ID, "")
        item = {
            "uid": uid,
            "appid": appid,
            "app": APP_NAMES.get(appid.lower(),
                                 appid.split(".")[-1].title() if appid else "Phone"),
            "title": attrs.get(ATTR_TITLE, "").strip(),
            "subtitle": attrs.get(ATTR_SUBTITLE, "").strip(),
            "message": attrs.get(ATTR_MESSAGE, "").strip(),
            "complete": True,
        }
        merged = STORE.add(item)
        if CFG["log_bodies"]:
            log("%s | %s: %s - %s" % (merged.get("cat"), merged["app"],
                                      merged["title"], merged["message"]))
        else:
            log("%s | %s from %r (%d chars)" % (
                merged.get("cat"), merged["app"], merged["title"],
                len(merged["message"])))


# --- signal wiring --------------------------------------------------------
def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter_path = find_adapter_path(bus, CFG["adapter"])
    if not adapter_path:
        log("adapter %s not found - is bluetooth powered?" % CFG["adapter"])
        return 1
    log("using adapter %s" % adapter_path)

    props = dbus.Interface(bus.get_object(BUS_NAME, adapter_path), DBUS_PROP_IFACE)
    props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
    props.Set(ADAPTER_IFACE, "Alias", dbus.String(CFG["local_name"]))
    props.Set(ADAPTER_IFACE, "Pairable", dbus.Boolean(True))
    props.Set(ADAPTER_IFACE, "PairableTimeout", dbus.UInt32(0))
    props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(True))
    props.Set(ADAPTER_IFACE, "DiscoverableTimeout", dbus.UInt32(0))

    agent = Agent(bus, AGENT_PATH)
    agent_mgr = dbus.Interface(bus.get_object(BUS_NAME, "/org/bluez"), AGENT_MGR_IFACE)
    agent_mgr.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
    try:
        agent_mgr.RequestDefaultAgent(AGENT_PATH)
    except dbus.exceptions.DBusException as exc:
        log("RequestDefaultAgent: %s" % exc)
    log("agent registered")

    adv = Advertisement(bus, ADV_PATH, CFG["local_name"])
    adv_mgr = dbus.Interface(bus.get_object(BUS_NAME, adapter_path), LE_ADV_MGR_IFACE)
    # registration itself is done by ensure_advertising() below, so the one
    # code path both starts and repairs the advertisement

    client = AncsClient(bus, adapter_path)

    def on_props_changed(interface, changed, invalidated, path=None):
        if interface == GATT_CHRC_IFACE and "Value" in changed:
            uuid = CHRC_UUID_CACHE.get(path)
            if uuid is None:
                try:
                    uuid = str(dbus.Interface(
                        bus.get_object(BUS_NAME, path), DBUS_PROP_IFACE
                    ).Get(GATT_CHRC_IFACE, "UUID")).lower()
                except Exception:                           # noqa: BLE001
                    return
                CHRC_UUID_CACHE[path] = uuid
            if uuid == NOTIFICATION_SOURCE:
                client.on_notification_source(changed["Value"])
            elif uuid == DATA_SOURCE:
                client.on_data_source(changed["Value"])

        elif interface == DEVICE_IFACE:
            if changed.get("ServicesResolved"):
                GLib.timeout_add(300, lambda: (client.try_attach(path), False)[1])
            elif "Connected" in changed and not changed["Connected"]:
                client.detach(path)
            elif changed.get("Paired"):
                log("paired with %s" % path)

    CHRC_UUID_CACHE = {}

    bus.add_signal_receiver(
        on_props_changed, dbus_interface=DBUS_PROP_IFACE,
        signal_name="PropertiesChanged", path_keyword="path")

    def on_iface_added(path, ifaces):
        if DEVICE_IFACE in ifaces:
            log("device appeared: %s" % path)

    bus.add_signal_receiver(on_iface_added, dbus_interface=DBUS_OM_IFACE,
                            signal_name="InterfacesAdded")

    client.scan_existing()

    # RECONNECT: iOS is the side that has to re-establish the ANCS link.
    #
    # The Pi version paged bonded phones itself every 30s with Device1.Connect()
    # and that is why it never came back on its own. For a DUAL-mode bond (which
    # is what pairing through iOS Settings always produces, via CTKD) BlueZ
    # routes Connect() over BR/EDR, and the iPhone exposes no classic profile
    # this host wants - so every single attempt died with
    #   org.bluez.Error.Failed: br-connection-profile-unavailable
    # (9600+ consecutive failures observed on the Pi). BlueZ does NOT fall back
    # to LE after that, so the transport ANCS actually needs was never tried.
    #
    # The correct model is the one every ANCS accessory uses: keep a connectable
    # LE advertisement soliciting ANCS on the air, and let iOS reconnect to it.
    # That is what ADVERTISING WATCHDOG below guarantees. The direct Connect()
    # is kept only as a low-rate fallback (it does occasionally win once the
    # phone has something to offer) - rate-limited so it cannot flood the log
    # or keep the controller busy paging a phone that is out of range.
    reconnect_fail = {}
    RECONNECT_MIN_INTERVAL = 300.0      # seconds between attempts per device

    def try_reconnect():
        if client.device_path is not None:
            return
        now = time.time()
        for path, ifaces in get_managed_objects(bus).items():
            dev = ifaces.get(DEVICE_IFACE)
            if not dev or not str(path).startswith(str(adapter_path) + "/"):
                continue
            if not dev.get("Paired") or dev.get("Connected"):
                continue
            p = str(path)
            last = reconnect_fail.get(p, {}).get("at", 0.0)
            if now - last < RECONNECT_MIN_INTERVAL:
                continue
            reconnect_fail.setdefault(p, {})["at"] = now

            def ok(p=p):
                reconnect_fail.pop(p, None)
                DIAG["last_reconnect_error"] = ""
                log("reconnected %s" % p)

            def err(exc, p=p):
                d = reconnect_fail.setdefault(p, {})
                n = d.get("n", 0) + 1
                d["n"] = n
                DIAG["last_reconnect_error"] = str(exc)
                DIAG["last_reconnect_at"] = time.time()
                # out of range / no classic profile is the normal case here
                if n <= 2 or n % 20 == 0:
                    log("reconnect to %s failed (%d): %s" % (p, n, exc))

            dbus.Interface(bus.get_object(BUS_NAME, p), DEVICE_IFACE).Connect(
                reply_handler=ok, error_handler=err, timeout=25)

    # --- ADVERTISING WATCHDOG ---------------------------------------------
    # Everything above depends on the ANCS solicitation actually being on the
    # air. bluetoothd releases the advertisement on its own in several cases
    # (adapter power cycle, a Release() from the daemon, an adapter reset), and
    # when that happens the phone simply has nothing to reconnect TO - which
    # looks exactly like "it's hit or miss". So track registration state and
    # put it back whenever it lapses.
    adv_state = {"registered": False, "busy": False, "obj": adv}

    def _adv_ok():
        adv_state["registered"] = True
        adv_state["busy"] = False
        DIAG["advertising"] = True
        DIAG["adv_registered_at"] = time.time()
        DIAG["adv_last_error"] = ""
        log("advertising as %r, soliciting ANCS" % CFG["local_name"])

    def _adv_err(exc):
        adv_state["registered"] = False
        adv_state["busy"] = False
        DIAG["advertising"] = False
        DIAG["adv_failures"] += 1
        DIAG["adv_last_error"] = str(exc)
        log("advertise FAILED: %s" % exc)

    def ensure_advertising():
        if adv_state["registered"] or adv_state["busy"]:
            return
        adv_state["busy"] = True
        try:
            adv_mgr.RegisterAdvertisement(adv.path, {},
                                          reply_handler=_adv_ok,
                                          error_handler=_adv_err)
        except Exception as exc:                            # noqa: BLE001
            _adv_err(exc)

    def on_adv_released():
        adv_state["registered"] = False
        DIAG["advertising"] = False
        log("advertisement was released - will re-register")

    adv.on_released = on_adv_released

    def set_discoverable(on):
        """Classic discoverability is only needed to GET paired - iOS will not
        list a pure-BLE peripheral in Settings, which is why BR/EDR has to be
        available at all.

        DEFAULT IS ALWAYS-ON, and that is deliberate. Two earlier attempts to
        be clever here both broke the phone:
          - gating on "has a bond" left the Pi invisible after a disconnect,
            with no way to re-pair from the phone alone;
          - gating on "is linked" turned out to drop the controller's
            CONNECTABLE flag with it, killing page scan - so iOS could not
            initiate a reconnection at all and the user had to connect by hand
            every single time.
        Staying discoverable costs a little more exposure on the address the
        bedroom Pi spoofs, which is already mitigated (no Car Thing link key
        here, no NAP service). Reliable auto-reconnect is worth more."""
        try:
            if bool(props.Get(ADAPTER_IFACE, "Discoverable")) != on:
                props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(on))
                log("classic discoverable -> %s" % on)
        except Exception as exc:                            # noqa: BLE001
            log("set_discoverable: %s" % exc)

    STATE["set_discoverable"] = set_discoverable

    def refresh_diag():
        """Snapshot what the radio is actually doing, for /api/status."""
        try:
            DIAG["adapter"] = str(adapter_path)
            DIAG["address"] = str(props.Get(ADAPTER_IFACE, "Address"))
            bonded, classic_only = [], False
            for path, ifaces in get_managed_objects(bus).items():
                dev = ifaces.get(DEVICE_IFACE)
                if not dev or not str(path).startswith(str(adapter_path) + "/"):
                    continue
                if not dev.get("Paired"):
                    continue
                entry = {
                    "path": str(path),
                    "alias": str(dev.get("Alias", "")),
                    "connected": bool(dev.get("Connected")),
                    "services_resolved": bool(dev.get("ServicesResolved")),
                    "rssi": int(dev["RSSI"]) if "RSSI" in dev else None,
                }
                bonded.append(entry)
                # connected, but the ANCS GATT client never attached: this is
                # the exact "I connect it by hand and still get nothing" case
                if entry["connected"] and client.device_path is None:
                    classic_only = True
            DIAG["bonded"] = bonded
            DIAG["classic_connected"] = classic_only

            # RECONCILE: a PropertiesChanged "Connected: false" can be missed
            # (bus hiccup, or the drop happening between scan_existing() and
            # the signal handler being wired at startup). Without this the
            # gateway keeps reporting linked:true against a phone that is gone,
            # so /healthz lies and every display sits polling a dead link.
            dp = client.device_path
            if dp is not None:
                still = next((b for b in bonded if b["path"] == str(dp)), None)
                if still is None or not still["connected"]:
                    log("device %s is no longer connected - detaching" % dp)
                    client.detach(dp)
            elif STORE.linked:
                # attached state already gone but the flag survived
                STORE.set_link(False)
        except Exception as exc:                            # noqa: BLE001
            log("refresh_diag: %s" % exc)

    def keepalive():
        try:
            ensure_advertising()
            set_discoverable(True if CFG.get("always_discoverable", True)
                             else (time.time() < STATE["pair_until"]
                                   or client.device_path is None))
            if not bool(props.Get(ADAPTER_IFACE, "Pairable")):
                props.Set(ADAPTER_IFACE, "Pairable", dbus.Boolean(True))
            if client.device_path is None:
                client.scan_existing()
                try_reconnect()
            refresh_diag()
        except Exception as exc:                            # noqa: BLE001
            log("keepalive: %s" % exc)
        return True

    keepalive()

    GLib.timeout_add_seconds(30, keepalive)

    threading.Thread(target=serve_http, args=(CFG["port"],), daemon=True).start()
    log("ready")
    GLib.MainLoop().run()
    return 0


# --- HTTP API -------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parts = self.path.split("?", 1)
        path = parts[0]
        if path in ("/api/notifications", "/api/notify", "/"):
            self._send(STORE.snapshot())
        elif path == "/healthz":
            self._send({"ok": True, "linked": STORE.linked})
        elif path == "/api/status":
            snap = STORE.snapshot(1)
            diag = dict(DIAG)
            diag["linked"] = snap["linked"]
            diag["device"] = snap["device"]
            diag["uptime_s"] = round(time.time() - DIAG["started"], 1)
            diag["local_name"] = CFG["local_name"]
            # a plain-English read of the state, so "is it working?" does not
            # require interpreting six booleans
            notif_ok = diag.get("notifying", {}).get("notification_source")
            if snap["linked"] and not notif_ok:
                diag["verdict"] = ("linked but the ANCS Notification Source is "
                                   "NOT subscribed - nothing can arrive. This is "
                                   "the silent failure: the link looks healthy "
                                   "and delivers nothing.")
            elif snap["linked"]:
                diag["verdict"] = "linked - notifications will arrive"
            elif diag["classic_connected"]:
                diag["verdict"] = ("phone is connected but ANCS is not attached: "
                                   "notification access was not granted, or the "
                                   "link is classic-only. Re-pair and allow "
                                   "'Share System Notifications'.")
            elif not diag["advertising"]:
                diag["verdict"] = ("NOT advertising - the phone has nothing to "
                                   "reconnect to. See adv_last_error.")
            elif diag["bonded"]:
                diag["verdict"] = ("advertising and bonded, waiting for the "
                                   "phone to come back in range")
            else:
                diag["verdict"] = ("advertising, no phone bonded yet - pair "
                                   "from iOS Settings > Bluetooth")
            self._send(diag)
        elif path == "/api/test":
            # inject a synthetic notification - lets the display chain be
            # verified end to end without waiting for a real call or text
            from urllib.parse import parse_qs
            q = parse_qs(parts[1] if len(parts) > 1 else "")

            def arg(name, default=""):
                return q.get(name, [default])[0]

            cat = arg("cat", "Social")
            catid = next((k for k, v in CATEGORIES.items() if v == cat), 4)
            item = {
                "uid": int(time.time() * 1000) % 2147483647,
                "catid": catid, "cat": cat,
                "app": arg("app", "Messages"), "appid": "test",
                "title": arg("title", "Test"),
                "subtitle": "", "message": arg("message", "Display test"),
                "ts": time.time(), "silent": False, "important": False,
                "call": catid == 1, "active": True, "complete": True,
                "test": True,
            }
            STORE.add(item)
            log("injected test notification uid=%d" % item["uid"])
            self._send({"ok": True, "injected": item})
        elif path == "/api/pair":
            # re-open classic discoverability so a phone can be (re-)paired
            mins = 5
            try:
                from urllib.parse import parse_qs
                mins = int(parse_qs(parts[1] if len(parts) > 1 else "")
                           .get("mins", ["5"])[0])
            except Exception:                               # noqa: BLE001
                pass
            mins = max(1, min(mins, 30))
            STATE["pair_until"] = time.time() + mins * 60
            if STATE["set_discoverable"]:
                STATE["set_discoverable"](True)
            log("pairing window opened for %d min" % mins)
            self._send({"ok": True, "discoverable_for_minutes": mins})
        elif path == "/api/test/clear":
            for i in STORE.snapshot(50)["items"]:
                if i.get("test"):
                    STORE.remove(i["uid"])
            self._send({"ok": True})
        else:
            self._send({"ok": False, "error": "not found"}, 404)

    def log_message(self, *args):
        pass


def serve_http(port):
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    log("http api on :%d" % port)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
