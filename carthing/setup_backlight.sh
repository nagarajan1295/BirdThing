#!/bin/bash
# BirdThing backlight. /tmp/bt_bright holds a brightness PERCENT 0-100 (set from the dashboard
# slider via the knob daemon). This panel's backlight is INVERTED (a higher raw value makes it
# DIMMER), so we write MAX-raw. /tmp/display_off blanks the screen (= write MAX on this panel).
BACKLIGHT="/sys/class/backlight/aml-bl/brightness"
FLAG="/tmp/display_off"
MODEF="/tmp/bt_bright"
MAX=255
cur=-1
clampw(){ w=$1; [ "$w" -lt 3 ] && w=3; [ "$w" -gt "$MAX" ] && w=$MAX; echo "$w"; }
while :; do
  if [ -f "$FLAG" ]; then
    # screen off: inverted panel -> MAX = dark
    [ "$cur" != "$MAX" ] && { echo "$MAX" > "$BACKLIGHT"; cur=$MAX; }
    sleep 0.3; continue
  fi
  p=$(cat "$MODEF" 2>/dev/null)
  case "$p" in *[!0-9]*|"") p=70 ;; esac     # default 70% if unset / legacy keyword
  [ "$p" -gt 100 ] && p=100
  raw=$(( p * MAX / 100 ))                    # desired physical brightness (100% = bright)
  target=$(clampw $(( MAX - raw )))           # INVERTED for this panel
  if [ "$cur" -lt 0 ]; then cur=$target; fi
  if [ "$target" -gt "$cur" ]; then cur=$(( cur + (target-cur+3)/4 )); else cur=$(( cur - (cur-target+3)/4 )); fi
  echo "$cur" > "$BACKLIGHT"
  sleep 0.4
done
