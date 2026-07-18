#!/usr/bin/env python3
# Clap -> Home Assistant toggle, fed mono int16 samples from birdthing_recv.
#
# Detects the sharp broadband impulse of a hand clap (loud, very short, quiet
# before it). A DOUBLE clap -- two claps DBL_MIN..DBL_MAX seconds apart -- fires
# an HA `<domain>.toggle` via REST in a BACKGROUND thread, so `light.toggle`
# flips the living-room lights on/off exactly like "clap twice on, clap twice
# off". Runs inside the recv process alongside BirdNET; it only READS the mono
# samples that already flow through, so it never touches the bird audio path.
#
# DEFENSIVE: every public entry point swallows its own errors. Nothing in here
# may ever raise into birdthing_recv and break the pipeline.
import json, os, time, threading, urllib.request

CFG_PATH = os.environ.get("CLAP_CFG", "/opt/birdthing/clap.json")
LOG_PATH = os.environ.get("CLAP_LOG", "/tmp/bt_clap.log")

# --- detector tuning (frame-based; overridable from clap.json "tune": {...}) ---
RATE       = 48000
FRAME      = 512      # ~10.7 ms analysis frame
PEAK_ABS   = 18000    # a clap must peak above this (mic AGC targets bg ~9000)
RATIO      = 5.0      # ...and be >= RATIO x the recent background level
BG_ALPHA   = 0.04     # EMA rate for the slow background level
REFRACTORY = 0.12     # ignore new onsets this long after one (a clap's decay/echo)
DBL_MIN    = 0.10     # two edges closer than this = same clap, not a pair
DBL_MAX    = 0.60     # ...farther apart than this = not a pair
COOLDOWN   = 1.20     # after a toggle, ignore claps this long (no re-trigger)

_np = None
try:
    import numpy as _np
except Exception:
    _np = None

# runtime state
_buf = b""            # leftover bytes < one FRAME
_bg = 1000.0          # background peak level (EMA)
_last_edge = 0.0      # time of the last accepted clap edge
_prev_edge = 0.0      # time of the edge before that (for pairing)
_muted_until = 0.0    # cooldown end after a toggle
_cfg = None
_cfg_mtime = 0.0


def _log(msg):
    try:
        with open(LOG_PATH, "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _load_cfg():
    # reload clap.json on change so tuning/enable can be edited without a restart
    global _cfg, _cfg_mtime, PEAK_ABS, RATIO, DBL_MIN, DBL_MAX, COOLDOWN
    try:
        m = os.path.getmtime(CFG_PATH)
    except Exception:
        _cfg = None
        return None
    if _cfg is not None and m == _cfg_mtime:
        return _cfg
    try:
        with open(CFG_PATH) as f:
            c = json.load(f)
        t = c.get("tune", {})
        PEAK_ABS = float(t.get("peak_abs", PEAK_ABS))
        RATIO    = float(t.get("ratio", RATIO))
        DBL_MIN  = float(t.get("dbl_min", DBL_MIN))
        DBL_MAX  = float(t.get("dbl_max", DBL_MAX))
        COOLDOWN = float(t.get("cooldown", COOLDOWN))
        _cfg, _cfg_mtime = c, m
        _log("config loaded: entity=%s enabled=%s" % (c.get("entity"), c.get("enabled")))
        return c
    except Exception as e:
        _log("config error: %s" % e)
        _cfg = None
        return None


def _fire_toggle():
    # POST /api/services/<domain>/toggle  (light.toggle flips on<->off)
    c = _load_cfg()
    if not c or not c.get("enabled") or not c.get("ha_token") or not c.get("entity"):
        _log("double-clap (no HA config / disabled -> not toggling)")
        return
    domain = c["entity"].split(".")[0]
    url = c["ha_url"].rstrip("/") + "/api/services/%s/toggle" % domain
    body = json.dumps({"entity_id": c["entity"]}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": "Bearer " + c["ha_token"],
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            _log("toggled %s -> HTTP %s" % (c["entity"], r.status))
    except Exception as e:
        _log("toggle FAILED for %s: %s" % (c["entity"], e))


def _on_edge(now):
    # an accepted clap edge at time `now`; decide single vs double
    global _prev_edge, _last_edge, _muted_until
    gap = now - _last_edge
    _prev_edge, _last_edge = _last_edge, now
    if DBL_MIN <= gap <= DBL_MAX:
        _muted_until = now + COOLDOWN
        _last_edge = 0.0            # consume the pair so a 3rd clap starts fresh
        _log("DOUBLE CLAP (gap=%.0fms)" % (gap * 1000))
        threading.Thread(target=_fire_toggle, daemon=True).start()


def feed(mono):
    """Feed a 1-D int16 numpy array of mono samples. Never raises."""
    global _buf, _bg, _last_edge, _muted_until
    if _np is None:
        return
    try:
        if mono is None or mono.size == 0:
            return
        # accumulate into whole FRAMEs
        raw = _buf + mono.astype("<i2").tobytes()
        n = len(raw) // (FRAME * 2)
        _buf = raw[n * FRAME * 2:]
        if n == 0:
            return
        frames = _np.frombuffer(raw[:n * FRAME * 2], dtype="<i2").reshape(n, FRAME)
        now = time.time()
        for fr in frames:
            peak = float(_np.abs(fr).max())
            now += FRAME / RATE
            if now < _muted_until:
                _bg = (1 - BG_ALPHA) * _bg + BG_ALPHA * min(peak, _bg * 3 + 200)
                continue
            is_clap = (peak >= PEAK_ABS and peak >= RATIO * _bg
                       and (now - _last_edge) >= REFRACTORY)
            if is_clap:
                _on_edge(now)
            else:
                # only quiet frames update the background (claps mustn't inflate it)
                _bg = (1 - BG_ALPHA) * _bg + BG_ALPHA * min(peak, _bg * 3 + 200)
    except Exception as e:
        _log("feed error: %s" % e)


# so the module can be smoke-tested on a WAV without the pipeline
if __name__ == "__main__":
    import sys, wave
    if _np is None:
        print("numpy required"); sys.exit(1)
    w = wave.open(sys.argv[1], "rb")
    ch = w.getnchannels()
    data = _np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    if ch == 2:
        data = data.reshape(-1, 2).mean(axis=1).astype("<i2")
    feed(data)
    print("done; see", LOG_PATH)
