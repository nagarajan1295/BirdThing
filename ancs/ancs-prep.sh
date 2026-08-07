#!/bin/bash
# Prepare hci0 on the BirdThing Pi for ANCS, and assert it on every boot.
#
# WHY DUAL MODE, not LE-only:
#   ANCS itself is pure BLE, and LE-only would neatly avoid the address clash
#   described below - but iOS will NOT list a pure-BLE peripheral in
#   Settings > Bluetooth, no matter how correct its ANCS solicitation is.
#   (Verified on air: AD type 0x15 with the real ANCS UUID, 100ms interval,
#   connectable, named - and the iPhone still showed nothing.) Classic
#   Bluetooth has to be available for the phone to discover and keep this
#   accessory. Once connected, the ANCS link itself rides LE.
#
# THE ADDRESS CLASH (live, mitigated - not eliminated):
#   This Pi's BD address DC:A6:32:62:53:01 is the address the BEDROOM Pi
#   spoofs to serve the WeatherThing Car Thing over BT PAN. With classic on,
#   this Pi answers paging on that address too. Mitigations:
#     - the Car Thing's stale bond has been REMOVED from this Pi, so it holds
#       no link key and a CT connection attempt cannot authenticate
#     - this Pi runs no NAP service (birdthing-btnap stays disabled)
#     - the gateway drops out of inquiry scan while a phone is linked
#   Do NOT re-enable birdthing-btnap or re-pair the Car Thing to this Pi.
#
# btmgmt GOTCHA: it silently ignores its command when it has no tty (exits 0
# doing nothing; under systemd it blocks until the unit times out). Every
# btmgmt call here therefore goes through `script -qec` to get a pty.
set -u
ADAPTER="${ADAPTER:-hci0}"
log() { echo "[ancs-prep] $*"; }
mgmt() { script -qec "btmgmt --index $ADAPTER $*" /dev/null >/dev/null 2>&1; }

# clear the rfkill soft-block left over from when Bluetooth was mothballed here
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

# Assert BR/EDR + SSP. Both are needed and neither is reliably restored:
# ControllerMode=dual in main.conf is overridden by whatever the kernel last
# had, and - the subtle one - power-cycling bredr CLEARS ssp. Without ssp the
# adapter only offers legacy PIN pairing and iOS will not pair with it at all.
need=""
case "$(settings)" in
    *br/edr*) ;;
    *) need="bredr" ;;
esac
case "$(settings)" in
    *ssp*) ;;
    *) need="$need ssp" ;;
esac

if [ -n "$need" ]; then
    log "asserting:$need"
    mgmt power off
    mgmt bredr on
    mgmt ssp on
    mgmt connectable on
    mgmt bondable on
    mgmt power on
    sleep 2
fi

log "$(settings)"
case "$(settings)" in
    *ssp*br/edr*|*br/edr*ssp*) log "ok - discoverable+pairable by iOS" ;;
    *) log "WARNING: br/edr and/or ssp missing - the iPhone will not pair" ;;
esac
log "done"
