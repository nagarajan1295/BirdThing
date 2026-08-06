#!/bin/bash
# Prepare hci0 on the BirdThing Pi for ANCS.
#
# All this does is clear the rfkill soft-block left over from when Bluetooth
# was mothballed on this Pi. The important part - forcing the controller to
# LE-ONLY - is done declaratively by bluetoothd via `ControllerMode = le` in
# /etc/bluetooth/main.conf, because btmgmt silently refuses to execute
# commands when it has no tty (it just exits 0 doing nothing, and under
# systemd it blocks until the unit times out).
#
# WHY LE-only matters: this Pi's real BD address is DC:A6:32:62:53:01 - the
# exact address the bedroom Pi spoofs to serve the WeatherThing Car Thing
# over BT PAN. With classic Bluetooth off, this adapter can never answer the
# Car Thing's paging or appear in its inquiry, so re-enabling Bluetooth here
# cannot break the WeatherThing. ANCS only needs BLE, so nothing is lost.
set -u
ADAPTER="${ADAPTER:-hci0}"
log() { echo "[ancs-prep] $*"; }

for rf in /sys/class/rfkill/rfkill*; do
    [ -e "$rf/type" ] || continue
    [ "$(cat "$rf/type")" = "bluetooth" ] || continue
    if [ "$(cat "$rf/soft")" != "0" ]; then
        echo 0 > "$rf/soft" 2>/dev/null && log "unblocked $(basename "$rf")"
    fi
done

# wait for the controller to come up under bluetoothd
for _ in $(seq 1 20); do
    hciconfig "$ADAPTER" >/dev/null 2>&1 && break
    sleep 1
done
hciconfig "$ADAPTER" up 2>/dev/null

state="$(hciconfig "$ADAPTER" 2>&1 | tr -s ' ')"
echo "$state" | sed 's/^/[ancs-prep] /'

# LE-only controllers report "Type: Primary" with no BR/EDR page scan; the
# authoritative check is the controller class - warn loudly if classic is live
if hciconfig "$ADAPTER" 2>/dev/null | grep -q 'ISCAN'; then
    log "WARNING: BR/EDR inquiry scan is ON - check ControllerMode=le in"
    log "WARNING: /etc/bluetooth/main.conf; MAC clash with bedroom Pi possible"
fi
log "done"
