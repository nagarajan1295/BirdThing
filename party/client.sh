#!/bin/sh
# party-client@<MAC-without-colons>: one snapclient into that speaker's BlueALSA PCM
MAC=$(echo "$1" | sed 's/../&:/g;s/:$//')
exec /usr/bin/snapclient -h 192.168.1.250 --hostID "party-$1" \
    --player alsa:buffer_time=400,fragments=8 -s "bluealsa:DEV=$MAC,PROFILE=a2dp"
