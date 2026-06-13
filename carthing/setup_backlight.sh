#!/bin/bash
# BirdThing backlight: auto-brightness from the tmd2772 ambient light sensor, with manual
# override modes. /tmp/display_off blanks the screen (toggled by the 'm' top button).
# /tmp/bt_bright = auto|low|mid|high (set from the dashboard Settings page via the knob daemon).
SENSOR="/sys/bus/iio/devices/iio:device0/in_illuminance0_input"
BACKLIGHT="/sys/class/backlight/aml-bl/brightness"
FLAG="/tmp/display_off"
MODEF="/tmp/bt_bright"
MIN=18; MAX=255
cur=-1
while :; do
  if [ -f "$FLAG" ]; then
    [ "$cur" != "0" ] && { echo 0 > "$BACKLIGHT"; cur=0; }
    sleep 0.3; continue
  fi
  mode=$(cat "$MODEF" 2>/dev/null); [ -z "$mode" ] && mode=auto
  case "$mode" in
    low)  b=45 ;;
    mid)  b=130 ;;
    high) b=255 ;;
    *)    lux=$(cat "$SENSOR" 2>/dev/null); [ -z "$lux" ] && lux=10
          b=$(( MIN + lux + lux/5 ))
          [ "$b" -gt "$MAX" ] && b=$MAX; [ "$b" -lt "$MIN" ] && b=$MIN ;;
  esac
  if [ "$cur" -lt 0 ]; then cur=$b; fi
  if [ "$b" -gt "$cur" ]; then cur=$(( cur + (b-cur+3)/4 )); else cur=$(( cur - (cur-b+3)/4 )); fi
  echo "$cur" > "$BACKLIGHT"
  sleep 0.4
done
