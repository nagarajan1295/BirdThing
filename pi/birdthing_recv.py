#!/usr/bin/env python3
# BirdThing Pi receiver: TCP 9000 -> gentle 250 Hz high-pass -> aplay -> ALSA loopback -> BirdNET.
# The high-pass removes sub-bass rumble (wind, traffic, AC hum) that masks faint birds, WITHOUT
# touching bird frequencies (birds are ~300 Hz and up), so unlike aggressive band/gate filtering it
# doesn't cost detections. Runs on the BirdNET venv python (numpy+scipy). On ANY error it falls back
# to plain passthrough so the pipeline can never break. Single writer to aplay.stdin (no deadlock).
import socket, subprocess

PORT = 9000
LOOPDEV = "hw:Loopback,0,0"
RATE = 48000
HP = 250.0
ORDER = 4

OK = True
try:
    import numpy as np
    from scipy.signal import butter, sosfilt, sosfilt_zi
    SOS = butter(ORDER, HP, btype="highpass", fs=RATE, output="sos")
    S = {"zi": sosfilt_zi(SOS), "buf": b""}
    print("high-pass %d Hz active (rumble removal)" % HP, flush=True)
except Exception as e:
    print("filter disabled (passthrough):", e, flush=True)
    OK = False


def process(data):
    if not OK:
        return data
    try:
        raw = S["buf"] + data
        n = len(raw) // 4                  # 4 bytes per stereo S16_LE frame
        u = n * 4
        S["buf"] = raw[u:]
        if n == 0:
            return b""
        a = np.frombuffer(raw[:u], dtype="<i2").reshape(-1, 2).astype(np.float32)
        mono = (a[:, 0] + a[:, 1]) * 0.5
        y, S["zi"] = sosfilt(SOS, mono, zi=S["zi"])
        y = np.clip(y, -32768.0, 32767.0).astype("<i2")
        st = np.empty((y.shape[0], 2), dtype="<i2")
        st[:, 0] = y
        st[:, 1] = y
        return st.tobytes()
    except Exception as e:
        print("filter error, passthrough:", e, flush=True)
        return data


def start_aplay():
    return subprocess.Popen(
        ["aplay", "-D", LOOPDEV, "-f", "S16_LE", "-r", "48000", "-c", "2", "-q"],
        stdin=subprocess.PIPE)


aplay = start_aplay()

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", PORT))
srv.listen(1)
print("birdthing_recv listening on %d" % PORT, flush=True)

while True:
    conn, addr = srv.accept()
    print("client connected:", addr, flush=True)
    if OK:
        S["buf"] = b""
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            if aplay.poll() is not None:
                aplay = start_aplay()
            out = process(data)
            if out:
                aplay.stdin.write(out)
                aplay.stdin.flush()
    except Exception as e:
        print("client error:", e, flush=True)
    finally:
        try: conn.close()
        except Exception: pass
        print("client disconnected", flush=True)
