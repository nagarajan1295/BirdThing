#!/usr/bin/env python3
"""roomloc hub — collects RSSI vectors from the nodes and decides which room
the phone is in, by fingerprint matching rather than absolute distance.

Fingerprinting is what makes this work with no anchor in the target rooms: we
never ask "how far is the phone from the kitchen", only "does the current
(livingroom, bedroom, ...) RSSI vector look more like the one recorded while
standing in the kitchen, or the one recorded in the bathroom".

Exposes:
  POST /report        node -> hub RSSI reports
  GET  /state         current vector + decided room  (Home Assistant polls this)
  GET  /              calibration UI (open it on the phone, walk, tap)
  POST /calibrate     {room, seconds} capture a fingerprint
  GET  /fingerprints  stored fingerprints
  POST /forget        {room} drop a room's fingerprints

Stock deps only: python3 stdlib.
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ABSENT = -105.0  # RSSI stand-in for "this node cannot hear the phone"

STATE_LOCK = threading.Lock()
NODES = {}          # node -> {rssi, age, ts}
FINGERPRINTS = {}   # room -> [vector, ...]
DECISION = {"room": None, "candidate": None, "since": 0.0, "confidence": 0.0,
            "changed_at": 0.0, "distances": {}}
CFG = {}


# --------------------------------------------------------------------------- io
def load_fingerprints(path):
    global FINGERPRINTS
    if os.path.exists(path):
        with open(path) as f:
            FINGERPRINTS = json.load(f)


def save_fingerprints(path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(FINGERPRINTS, f, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------------- matching
def current_vector(node_names):
    now = time.time()
    vec = {}
    for n in node_names:
        d = NODES.get(n)
        if d and d["rssi"] is not None and (now - d["ts"]) < CFG["stale_after"]:
            vec[n] = float(d["rssi"])
        else:
            vec[n] = ABSENT
    return vec


def distance(vec, fp, node_names):
    return sum((vec[n] - fp.get(n, ABSENT)) ** 2 for n in node_names) ** 0.5


def decide(node_names):
    """Nearest-fingerprint room, with a margin gate and a dwell timer.

    Two guards against flapping mid-song: the winner must beat the runner-up by
    `margin` dB, and it must hold that win for `dwell` seconds before we accept.
    """
    vec = current_vector(node_names)
    if all(v == ABSENT for v in vec.values()):
        return vec, None, {}, 0.0

    scored = []
    for room, samples in FINGERPRINTS.items():
        if not samples:
            continue
        best = min(distance(vec, s, node_names) for s in samples)
        scored.append((best, room))
    if not scored:
        return vec, None, {}, 0.0
    scored.sort()
    dists = {r: round(d, 1) for d, r in scored}

    best_d, best_room = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else best_d + 999
    margin = runner_up - best_d
    confidence = max(0.0, min(1.0, margin / CFG["margin"]))

    now = time.time()
    if margin < CFG["margin"]:
        # Ambiguous -- hold whatever room we last committed to.
        DECISION["candidate"] = None
        return vec, DECISION["room"], dists, confidence

    if DECISION["candidate"] != best_room:
        DECISION["candidate"] = best_room
        DECISION["since"] = now
    if best_room != DECISION["room"] and (now - DECISION["since"]) >= CFG["dwell"]:
        DECISION["room"] = best_room
        DECISION["changed_at"] = now
    return vec, DECISION["room"], dists, confidence


def decision_loop(node_names):
    while True:
        with STATE_LOCK:
            vec, room, dists, conf = decide(node_names)
            DECISION["distances"] = dists
            DECISION["confidence"] = round(conf, 2)
            DECISION["vector"] = vec
        time.sleep(1.0)


# -------------------------------------------------------------------------- http
PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>roomloc calibration</title>
<style>body{font:16px system-ui;margin:0;padding:16px;background:#111;color:#eee}
h1{font-size:19px;margin:0 0 4px}p.sub{color:#888;margin:0 0 16px;font-size:13px}
table{width:100%;border-collapse:collapse;margin-bottom:16px}
td{padding:6px 4px;border-bottom:1px solid #262626;font-variant-numeric:tabular-nums}
td.v{text-align:right;color:#7dd3fc}
button{font:600 16px system-ui;padding:14px;width:100%;margin-bottom:8px;border:0;
border-radius:10px;background:#1f6feb;color:#fff}button.g{background:#262626;color:#bbb}
#room{font-size:26px;font-weight:700;margin:8px 0}#msg{color:#4ade80;min-height:20px;font-size:14px}
input{font:16px system-ui;padding:12px;width:100%;box-sizing:border-box;margin-bottom:8px;
border-radius:10px;border:1px solid #333;background:#1a1a1a;color:#eee}</style>
<h1>roomloc</h1><p class=sub>Stand still in a room, name it, tap Capture. Do each room 2-3 times.</p>
<div id=room>-</div><table id=t></table>
<input id=name placeholder="room name e.g. kitchen">
<button onclick=cap()>Capture 12s fingerprint</button>
<button class=g onclick=forget()>Forget this room</button>
<div id=msg></div>
<script>
async function tick(){
 const s=await (await fetch('/state')).json();
 document.getElementById('room').textContent=(s.room||'unknown')+' ('+s.confidence+')';
 document.getElementById('t').innerHTML=Object.entries(s.vector||{}).map(([k,v])=>
  `<tr><td>${k}</td><td class=v>${v<=-105?'--':v.toFixed(1)}</td></tr>`).join('')
  +Object.entries(s.distances||{}).map(([k,v])=>
  `<tr><td style=color:#777>fit: ${k}</td><td class=v style=color:#777>${v}</td></tr>`).join('');
}
async function cap(){const r=document.getElementById('name').value.trim();if(!r)return;
 document.getElementById('msg').textContent='capturing '+r+'... hold still';
 const x=await (await fetch('/calibrate',{method:'POST',body:JSON.stringify({room:r,seconds:12})})).json();
 document.getElementById('msg').textContent=x.ok?('saved '+r+' ('+x.count+' fingerprints)'):('error: '+x.error);}
async function forget(){const r=document.getElementById('name').value.trim();if(!r)return;
 await fetch('/forget',{method:'POST',body:JSON.stringify({room:r})});
 document.getElementById('msg').textContent='forgot '+r;}
setInterval(tick,1000);tick();
</script>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/state":
            with STATE_LOCK:
                out = {
                    "room": DECISION["room"],
                    "confidence": DECISION["confidence"],
                    "vector": DECISION.get("vector", {}),
                    "distances": DECISION["distances"],
                    "changed_at": DECISION["changed_at"],
                    "seconds_in_room": round(time.time() - DECISION["changed_at"], 1)
                    if DECISION["changed_at"] else None,
                    "nodes": {k: {"rssi": v["rssi"], "src": v.get("src"),
                                  "age": round(time.time() - v["ts"], 1)}
                              for k, v in NODES.items()},
                    "rooms_known": sorted(FINGERPRINTS),
                }
            return self._send(200, json.dumps(out))
        if self.path == "/fingerprints":
            return self._send(200, json.dumps(FINGERPRINTS, indent=1))
        self._send(404, "{}")

    def do_POST(self):
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, json.dumps({"error": "bad json"}))

        if self.path == "/report":
            node = body.get("node")
            if not node:
                return self._send(400, json.dumps({"error": "no node"}))
            with STATE_LOCK:
                NODES[node] = {"rssi": body.get("rssi"), "age": body.get("age"),
                               "src": body.get("src"), "ts": time.time()}
            return self._send(200, json.dumps({"ok": True}))

        if self.path == "/calibrate":
            room = (body.get("room") or "").strip().lower()
            secs = float(body.get("seconds") or 12)
            if not room:
                return self._send(400, json.dumps({"ok": False, "error": "no room"}))
            samples = []
            end = time.time() + secs
            while time.time() < end:
                with STATE_LOCK:
                    v = current_vector(CFG["nodes"])
                if not all(x == ABSENT for x in v.values()):
                    samples.append(v)
                time.sleep(1.5)
            if not samples:
                return self._send(200, json.dumps({"ok": False, "error": "phone not seen"}))
            # Average the run into one fingerprint; append so a room can hold
            # several (near the door, at the sink, ...) without them blurring.
            avg = {n: round(sum(s[n] for s in samples) / len(samples), 1)
                   for n in CFG["nodes"]}
            with STATE_LOCK:
                FINGERPRINTS.setdefault(room, []).append(avg)
                save_fingerprints(CFG["store"])
                count = len(FINGERPRINTS[room])
            return self._send(200, json.dumps({"ok": True, "room": room,
                                               "fingerprint": avg, "count": count}))

        if self.path == "/forget":
            room = (body.get("room") or "").strip().lower()
            with STATE_LOCK:
                FINGERPRINTS.pop(room, None)
                save_fingerprints(CFG["store"])
                if DECISION["room"] == room:
                    DECISION["room"] = None
            return self._send(200, json.dumps({"ok": True}))

        self._send(404, "{}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8093)
    p.add_argument("--nodes", required=True, help="comma-separated node names")
    p.add_argument("--store", default="/opt/roomloc/fingerprints.json")
    p.add_argument("--dwell", type=float, default=8.0,
                   help="seconds a new room must win before we commit")
    p.add_argument("--margin", type=float, default=6.0,
                   help="dB the best room must beat the runner-up by")
    p.add_argument("--stale-after", type=float, default=45.0)
    a = p.parse_args()

    CFG.update(nodes=[n.strip() for n in a.nodes.split(",") if n.strip()],
               store=a.store, dwell=a.dwell, margin=a.margin,
               stale_after=a.stale_after)
    os.makedirs(os.path.dirname(a.store), exist_ok=True)
    load_fingerprints(a.store)

    threading.Thread(target=decision_loop, args=(CFG["nodes"],), daemon=True).start()
    print(f"roomloc hub on :{a.port} nodes={CFG['nodes']} rooms={sorted(FINGERPRINTS)}",
          flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
