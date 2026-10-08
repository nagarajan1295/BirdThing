#!/bin/sh
# Lock the bedroom Pi onto the router's 5 GHz band: on 2.4 GHz its combo
# WiFi/BT chip starves WiFi while it streams A2DP (snapclient TCP drops,
# time-sync timeouts). Self-reverting: no gateway within 60 s -> back to auto.
C=SpectrumSetup-5F
GW=$(ip route | awk '/^default/ {print $3; exit}')
LOG=/var/log/party-wifi5.log
echo "$(date '+%F %T') switching to 5 GHz (gw $GW)" >> $LOG
nmcli con modify "$C" 802-11-wireless.band a
nmcli con up "$C" >> $LOG 2>&1
for i in 1 2 3 4 5 6; do
    sleep 10
    if ping -c2 -W2 "$GW" > /dev/null 2>&1; then
        echo "$(date '+%F %T') OK: $(nmcli -t -f IN-USE,FREQ,SIGNAL dev wifi | grep '^\*')" >> $LOG
        exit 0
    fi
done
echo "$(date '+%F %T') no gateway on 5 GHz - rolling back to auto band" >> $LOG
nmcli con modify "$C" 802-11-wireless.band ""
nmcli con up "$C" >> $LOG 2>&1
