#!/bin/bash
# Prepare hci0 on the Mac mini for ANCS, and assert it on every boot.
#
# This host replaced the BirdThing Pi as the phone-facing end: its Broadcom
# BCM20702 (Apple 05ac:8289, HCI 4.0) is a dedicated USB radio with the Mac's
# own antenna, rather than the Pi's SoC radio sharing a PCB antenna with WiFi,
# and it starts with ZERO existing bonds - so none of the Pi's address-clash
# mitigations (it spoofs the bedroom Pi's BD address) apply here at all.
#
# WHY DUAL MODE, not LE-only:
#   ANCS itself is pure BLE, but iOS will not list a pure-BLE peripheral in
#   Settings > Bluetooth (verified on air on the Pi: correct AD type 0x15, real
#   ANCS UUID, 100ms interval, connectable, named - the iPhone showed nothing).
#   Classic has to be available for the phone to DISCOVER the accessory. Once
#   connected, the ANCS link itself rides LE, and pairing over classic derives
#   the LE keys via CTKD.
#
# btmgmt GOTCHA: it silently ignores its command when it has no tty (exits 0
# doing nothing; under systemd it blocks until the unit times out). Every
# btmgmt call here therefore goes through `script -qec` to get a pty.
set -u
ADAPTER="${ADAPTER:-hci0}"
log() { echo "[ancs-prep] $*"; }
mgmt() { script -qec "btmgmt --index $ADAPTER $*" /dev/null >/dev/null 2>&1; }

for rf in /sys/class/rfkill/rfkill*; do
    [ -e "$rf/type" ] || continue
    [ "$(cat "$rf/type")" = "bluetooth" ] || continue
    if [ "$(cat "$rf/soft")" != "0" ]; then
        echo 0 > "$rf/soft" 2>/dev/null && log "unblocked $(basename "$rf")"
    fi
done

for _ in $(seq 1 30); do
    hciconfig "$ADAPTER" >/dev/null 2>&1 && break
    sleep 1
done

settings() { script -qec "btmgmt --index $ADAPTER info" /dev/null 2>/dev/null \
             | grep -m1 'current settings:'; }

# Assert BR/EDR + SSP + CONNECTABLE + BONDABLE.
#   ssp:         power-cycling bredr CLEARS it, and without it the adapter
#                offers only legacy PIN pairing, which iOS refuses outright.
#   connectable: this is page scan. Without it the iPhone cannot initiate a
#                reconnection at all - the single most common cause of "I have
#                to connect it by hand every time". It is NOT implied by
#                br/edr or ssp and has been silently dropped before.
#   bondable:    the mini boots without it (verified: current settings were
#                just "powered ssp br/edr le secure-conn"), so pairing would
#                fail before this script existed.
need=""
for flag in br/edr ssp connectable bondable; do
    case "$(settings)" in
        *"$flag"*) ;;
        *) need="$need $flag" ;;
    esac
done

if [ -n "$need" ]; then
    log "asserting:$need"
    mgmt power off
    mgmt bredr on
    mgmt ssp on
    mgmt connectable on
    mgmt bondable on
    mgmt le on
    mgmt power on
    sleep 2
fi

# CLASS OF DEVICE - this decides whether iOS offers "Share System Notifications"
#
# A desktop host advertises itself as Computer/Laptop (the mini booted as
# 0x00010c). iOS does not offer notification sharing to a device it classifies
# as a COMPUTER - it treats it as a peer machine rather than an accessory, so
# the toggle simply never appears under the (i) and ANCS can never be granted.
# The BirdThing Pi, which worked, presented 0x400000 = Miscellaneous device
# with the Telephony service class. Match that exactly.
#
# main.conf's `Class` only carries the device-class half; the service-class bits
# have to be written over HCI, and bluetoothd resets them on restart - so assert
# the full 24-bit value here on every boot.
WANT_CLASS="${WANT_CLASS:-0x400000}"
cur_class="$(hciconfig -a "$ADAPTER" 2>/dev/null | sed -n 's/.*Class: \(0x[0-9a-fA-F]*\).*/\1/p' | head -1)"
if [ "$cur_class" != "$WANT_CLASS" ]; then
    log "class of device $cur_class -> $WANT_CLASS"
    hciconfig "$ADAPTER" class "$WANT_CLASS" 2>/dev/null
    sleep 1
fi
log "class: $(hciconfig -a "$ADAPTER" 2>/dev/null | grep -m1 'Class:')"

log "$(settings)"
s="$(settings)"
for flag in br/edr ssp connectable bondable le; do
    case "$s" in
        *"$flag"*) ;;
        *) log "WARNING: '$flag' missing - iPhone pairing/auto-reconnect will fail" ;;
    esac
done
log "done"
