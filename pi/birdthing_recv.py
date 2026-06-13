#!/usr/bin/env python3
# BirdThing Pi receiver: listens on TCP 9000, pipes incoming audio from the Car Thing
# daemon into a persistent aplay feeding the ALSA loopback (BirdNET records the other end).
# Single writer to aplay.stdin (no helper threads) so a slow/blocked aplay can never
# deadlock against a second writer. When no client is connected, aplay simply waits on
# stdin, keeping the loopback open; arecord on the other end records silence meanwhile.
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
print("birdthing_recv listening on %d" % PORT, flush=True)

while True:
    conn, addr = srv.accept()
    print("client connected:", addr, flush=True)
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            if aplay.poll() is not None:        # aplay died -> respawn
                aplay = start_aplay()
            aplay.stdin.write(data)
            aplay.stdin.flush()
    except Exception as e:
        print("client error:", e, flush=True)
    finally:
        try: conn.close()
        except Exception: pass
        print("client disconnected", flush=True)
