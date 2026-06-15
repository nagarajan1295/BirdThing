#!/usr/bin/env python3
# BirdThing Pi receiver: TCP -> noise reduction -> aplay -> ALSA loopback -> BirdNET.
# Noise reduction = gentle bandpass (350 Hz - 12 kHz, keeps low birds like doves/owls and high
# warblers, drops sub-bass rumble/AC hum and ultrasonic hiss) + spectral gating that subtracts the
# steady background (overlap-add STFT). Conservative gate floor so it can never gut a real call.
# Run with the BirdNET venv python (numpy). Single writer to aplay.stdin. Passthrough on any error.
import socket, subprocess

PORT = 9000
LOOPDEV = "hw:Loopback,0,0"
RATE = 48000
HP, LP = 350.0, 12000.0
N, H = 1024, 256            # frame, hop (75% overlap)
GATE_BETA = 0.0            # spectral gate OFF (=bandpass only) — avoids distortion that can cause
GATE_FLOOR = 0.18         # mis-IDs; raise BETA to ~1.5 to re-enable spectral noise subtraction

OK = True
try:
    import numpy as np
    WIN = np.hanning(N).astype(np.float32)
    WIN2 = (WIN * WIN).astype(np.float32)
    FREQ = np.fft.rfftfreq(N, 1.0 / RATE)
    BAND = ((FREQ >= HP) & (FREQ <= LP)).astype(np.float32)
    S = {"inbuf": np.zeros(0, np.float32),
         "asig": np.zeros(N, np.float32),
         "awin": np.zeros(N, np.float32),
         "noise": None, "bytebuf": b""}
    print("noise reduction active (bandpass %.0f-%.0f Hz + spectral gate)" % (HP, LP), flush=True)
except Exception as e:
    print("noise reduction disabled (passthrough):", e, flush=True)
    OK = False


def process(data):
    if not OK:
        return data
    try:
        raw = S["bytebuf"] + data
        nfr = len(raw) // 4                 # 4 bytes per stereo S16_LE frame
        usable = nfr * 4
        S["bytebuf"] = raw[usable:]
        if nfr:
            a = np.frombuffer(raw[:usable], dtype="<i2").reshape(-1, 2).astype(np.float32)
            mono = (a[:, 0] + a[:, 1]) * 0.5
            S["inbuf"] = np.concatenate([S["inbuf"], mono])
        out = []
        while len(S["inbuf"]) >= N:
            frame = S["inbuf"][:N] * WIN
            X = np.fft.rfft(frame)
            mag = np.abs(X)
            nz = S["noise"]
            if nz is None:
                nz = mag.copy()
            else:
                nz = np.minimum(mag, nz * 1.001)    # track the spectral noise floor (slow rise)
            S["noise"] = nz
            mask = np.clip((mag - GATE_BETA * nz) / (mag + 1e-6), GATE_FLOOR, 1.0)
            y = np.fft.irfft(X * mask * BAND, N).astype(np.float32) * WIN
            S["asig"][:N] += y
            S["awin"][:N] += WIN2
            seg = S["asig"][:H] / np.maximum(S["awin"][:H], 1e-6)
            out.append(seg.copy())
            S["asig"][:N - H] = S["asig"][H:]; S["asig"][N - H:] = 0
            S["awin"][:N - H] = S["awin"][H:]; S["awin"][N - H:] = 0
            S["inbuf"] = S["inbuf"][H:]
        if not out:
            return b""
        y = np.clip(np.concatenate(out), -32768.0, 32767.0).astype("<i2")
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
        S["inbuf"] = np.zeros(0, np.float32)
        S["asig"][:] = 0; S["awin"][:] = 0
        S["noise"] = None; S["bytebuf"] = b""
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
