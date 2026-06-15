#!/usr/bin/env python3
# BirdThing Pi receiver: TCP 9000 -> aplay -> ALSA loopback -> BirdNET.
# PLAIN PASSTHROUGH — no audio filtering. BirdNET sees the raw mic, which picks up obvious birds
# best. (Bandpass/spectral-gate versions are in git history if ever wanted again.)
# Single writer to aplay.stdin so a slow aplay can't deadlock.
import socket, subprocess

PORT = 9000
LOOPDEV = "hw:Loopback,0,0"


def start_aplay():
    return subprocess.Popen(
        ["aplay", "-D", LOOPDEV, "-f", "S16_LE", "-r", "48000", "-c", "2", "-q"],
        stdin=subprocess.PIPE)


aplay = start_aplay()

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", PORT))
srv.listen(1)
print("birdthing_recv (passthrough) listening on %d" % PORT, flush=True)

while True:
    conn, addr = srv.accept()
    print("client connected:", addr, flush=True)
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            if aplay.poll() is not None:
                aplay = start_aplay()
            aplay.stdin.write(data)
            aplay.stdin.flush()
    except Exception as e:
        print("client error:", e, flush=True)
    finally:
        try: conn.close()
        except Exception: pass
        print("client disconnected", flush=True)
