#!/bin/bash
# BirdThing backlight. /tmp/bt_bright holds a brightness PERCENT 0-100 (set from the dashboard
# slider via the knob daemon). This panel's backlight is INVERTED (a higher raw value makes it
# DIMMER), so we write MAX-raw. /tmp/display_off blanks the screen (= write MAX on this panel).
#
# FLICKER FIX (2026-06-27): writing the aml-bl sysfs node re-latches the PWM and causes a brief
# visible FLASH. The old loop wrote every 0.4s unconditionally, so the screen blinked forever in
# steady state. Now we ONLY write when the value actually CHANGES (write-on-change): a smooth fade
# while ramping to a new target, then total silence once settled -> no more flashing.
BACKLIGHT="/sys/class/backlight/aml-bl/brightness"
FLAG="/tmp/display_off"
MODEF="/tmp/bt_bright"
MAX=255
cur=-1
last=-1

# nocturned (the Nocturne UI daemon) runs its OWN auto-dim ramp that continuously pulls the
# backlight toward dark, fighting our writes -- THIS is the long-standing screen flicker. We run
# our own Chromium kiosk (not nocturne-ui) and control brightness here, so stop nocturned once.
# It starts again on the next boot (before this script), then we stop it again -- BT/display are
# unaffected (the BT PAN link is bt-pan.sh, the display is Chromium; both run without nocturned).
supervisorctl stop nocturned >/dev/null 2>&1
clampw(){ w=$1; [ "$w" -lt 3 ] && w=3; [ "$w" -gt "$MAX" ] && w=$MAX; echo "$w"; }
write_if_changed(){ [ "$cur" -ne "$last" ] && { echo "$cur" > "$BACKLIGHT"; last=$cur; }; }
while :; do
  if [ -f "$FLAG" ]; then
    cur=$MAX; write_if_changed                 # screen off: inverted panel -> MAX = dark
    sleep 0.3; continue
  fi
  p=$(cat "$MODEF" 2>/dev/null)
  case "$p" in *[!0-9]*|"") p=70 ;; esac       # default 70% if unset / legacy keyword
  [ "$p" -gt 100 ] && p=100
  [ "$p" -lt 8 ] && p=8                         # never fully black via brightness ('m' button blanks)
  raw=$(( p * MAX / 100 ))                      # desired physical brightness (100% = bright)
  target=$(clampw $(( MAX - raw )))             # INVERTED for this panel
  if [ "$cur" -lt 0 ]; then cur=$target; fi
  if [ "$cur" -ne "$target" ]; then            # ramp toward target ONLY while it differs
    if [ "$target" -gt "$cur" ]; then cur=$(( cur + (target-cur+3)/4 )); else cur=$(( cur - (cur-target+3)/4 )); fi
  fi
  write_if_changed                             # writes ONLY on change -> no steady-state flashing
  if [ "$cur" -eq "$target" ]; then sleep 0.6; else sleep 0.06; fi   # idle: quiet; fading: fast+smooth
done
