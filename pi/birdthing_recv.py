#!/usr/bin/env python3
# BirdThing Pi receiver: listens on TCP 9000, applies a bandpass filter to reduce ambient
# noise (low rumble: wind/traffic/HVAC hum, and high hiss), then pipes the cleaned audio into
# a persistent aplay feeding the ALSA loopback (BirdNET records the other end).
# Single writer to aplay.stdin (no helper threads) so a slow/blocked aplay can never deadlock.
# Run with the BirdNET venv python (has numpy+scipy). If filtering can't load, it passes audio
# through unchanged so the pipeline never breaks.
import socket, subprocess

PORT = 9000
LOOPDEV = "hw:Loopback,0,0"
RATE = 48000
HP, LP, ORDER = 1800.0, 10000.0, 4   # bird song band ~1.8-10 kHz

FILTER = True
try:
    import numpy as np
    from scipy.signal import butter, sosfilt, sosfilt_zi
    SOS = butter(ORDER, [HP, LP], btype="bandpass", fs=RATE, output="sos")
    _ZI = sosfilt_zi(SOS)
    _state = {"zi": _ZI.copy(), "buf": b""}
    print("bandpass filter active (%.0f-%.0f Hz)" % (HP, LP), flush=True)
except Exception as e:
    print("bandpass disabled (passthrough):", e, flush=True)
    FILTER = False


def process(data):
    if not FILTER:
        return data
    try:
        buf = _state["buf"] + data
        nframes = len(buf) // 4              # 4 bytes per stereo S16_LE frame
        usable = nframes * 4
        _state["buf"] = buf[usable:]
        if nframes == 0:
            return b""
        a = np.frombuffer(buf[:usable], dtype="<i2").reshape(-1, 2).astype(np.float32)
        mono = (a[:, 0] + a[:, 1]) * 0.5
        y, _state["zi"] = sosfilt(SOS, mono, zi=_state["zi"])
        y = np.clip(y, -32768.0, 32767.0).astype("<i2")
        out = np.empty((y.shape[0], 2), dtype="<i2")
        out[:, 0] = y
        out[:, 1] = y
        return out.tobytes()
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
    if FILTER:
        _state["buf"] = b""              # reset partial-frame buffer per connection
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            if aplay.poll() is not None:        # aplay died -> respawn
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
