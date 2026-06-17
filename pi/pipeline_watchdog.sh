#!/bin/bash
# BirdThing pipeline self-repair. The audio chain (CT PDM mic -> TCP -> Pi recv -> ALSA loopback ->
# BirdNET) occasionally stalls "silently": services stay active but the mic goes dead, so BirdNET
# hears silence and stops IDing. A healthy mic (with AGC) always yields a loud loopback signal, so a
# near-silent loopback reliably means "stuck". When detected, hard-restart the whole chain.
PY=/home/birdpi/BirdNET-Pi/birdnet/bin/python3
LOG=/tmp/birdthing-watchdog.log

peak=$("$PY" - <<'EOF'
import glob, os, wave, numpy as np
fs = sorted(glob.glob('/home/birdpi/BirdSongs/StreamData/*.wav'), key=os.path.getmtime)[-3:]
mx = 0
for f in fs:
    try:
        w = wave.open(f); d = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if d.size:
            mx = max(mx, int(np.abs(d).max()))
    except Exception:
        pass
print(mx)
EOF
)
peak=${peak:-0}
ts=$(date '+%F %T')
if [ "$peak" -lt 30 ]; then
    echo "$ts STALL (loopback peak=$peak) -> hard-resetting audio chain" >> "$LOG"
    sshpass -p superbird ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 \
        superbird@192.168.7.2 'sudo systemctl stop birdmic; sleep 2; sudo systemctl start birdmic' 2>/dev/null
    sudo systemctl restart birdthing-recv
    sudo systemctl restart birdnet_analysis
    echo "$ts hard-reset done" >> "$LOG"
else
    echo "$ts ok (peak=$peak)" >> "$LOG"
fi
# keep the log small
tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" 2>/dev/null
