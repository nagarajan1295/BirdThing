#!/usr/bin/env python3
# Clap -> Home Assistant toggle, fed mono int16 samples from birdthing_recv.
#
# Detects the sharp broadband impulse of a hand clap (loud, very short, quiet
# before it). A DOUBLE clap -- two claps DBL_MIN..DBL_MAX seconds apart -- fires
# an HA `<domain>.toggle` on every configured entity via REST in a BACKGROUND
# thread, so `switch.toggle` / `light.toggle` flips them on/off exactly like
# "clap twice on, clap twice off". Runs inside the recv process alongside
# BirdNET; it only READS the mono samples that already flow through, so it never
# touches the bird audio path.
#
# DETECTION IS RATIO-BASED so it survives the Car Thing mic's auto-gain: a clap
# is scored against the *rolling background level*, not a fixed absolute (a fixed
# threshold silently stops working when the room gets louder and AGC drops the
# gain). Two dials in clap.json, both live-editable from the dashboard:
#   sensitivity 1..10  -> how far above background a clap must jump (+ a floor)
#   boost       1..8   -> gain applied to the detection signal (for a quiet/far mic)
#
# DEFENSIVE: every public entry point swallows its own errors. Nothing in here
# may ever raise into birdthing_recv and break the pipeline.
import json, os, time, threading, urllib.request, datetime

CFG_PATH  = os.environ.get("CLAP_CFG", "/opt/birdthing/clap.json")
LOG_PATH  = os.environ.get("CLAP_LOG", "/tmp/bt_clap.log")
STAT_PATH = os.environ.get("CLAP_STAT", "/tmp/bt_clap_stat.json")

# --- fixed detector constants ---
RATE       = 48000
FRAME      = 512      # ~10.7 ms analysis frame
BG_ALPHA   = 0.04     # EMA rate for the slow background level
REFRACTORY = 0.12     # ignore new onsets this long after one (a clap's decay/echo)
DBL_MIN    = 0.09     # two edges closer than this = same clap, not a pair
STAT_EVERY = 0.4      # how often to publish the live tuning stats

_np = None
try:
    import numpy as _np
except Exception:
    _np = None

# runtime state
_buf = b""            # leftover bytes < one FRAME
_bg = 1000.0          # background peak level (EMA), on the boosted signal
_prev_pk = 0.0        # previous frame's boosted peak (for the "quiet before" onset gate)
_last_edge = 0.0      # time of the last accepted clap edge
_last_double = 0.0    # time of the last accepted double clap
_muted_until = 0.0    # cooldown end after a toggle
_singles = 0          # counters (for the dashboard)
_doubles = 0
_pk_hold = 0.0        # loudest raw peak since the last stat publish
_stat_t = 0.0
_cfg = None
_cfg_mtime = 0.0


def _log(msg):
    try:
        with open(LOG_PATH, "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _sens_params(s):
    # sensitivity 1 (strict) .. 10 (twitchy) -> (min_peak_floor, ratio_above_bg)
    s = max(1.0, min(10.0, float(s)))
    frac = (s - 1) / 9.0
    min_peak = 14000 - frac * 10500      # 14000 .. 3500
    ratio    = 7.0 - frac * 4.8          # 7.0 .. 2.2
    return min_peak, ratio


def _load_cfg():
    # reload clap.json on change so tuning/enable can be edited without a restart
    global _cfg, _cfg_mtime
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
        _cfg, _cfg_mtime = c, m
        _log("config: entities=%s enabled=%s sens=%s boost=%s after_sunset=%s pre_min=%s"
             % (_entities(c), c.get("enabled"), c.get("sensitivity", 6),
                c.get("boost", 1.0), c.get("after_sunset", False), c.get("pre_sunset_min", 0)))
        return c
    except Exception as e:
        _log("config error: %s" % e)
        _cfg = None
        return None


def _entities(c):
    e = c.get("entities")
    if isinstance(e, list) and e:
        return [x for x in e if x and "." in x]
    if c.get("entity"):
        return [c["entity"]]
    return []


_sun = {"t": 0.0, "night": None, "set": None}   # cached HA sun.sun (state + next sunset)

def _sun_state(c):
    # HA sun.sun: is it currently below the horizon, and when is the next actual
    # sunset (next_setting, the horizon crossing -- NOT next_dusk which is ~25 min
    # later). Uses the location HA is configured with; cached 2 min.
    now = time.time()
    if _sun["night"] is not None and now - _sun["t"] < 120:
        return _sun
    try:
        req = urllib.request.Request(
            c["ha_url"].rstrip("/") + "/api/states/sun.sun",
            headers={"Authorization": "Bearer " + c["ha_token"]})
        s = json.load(urllib.request.urlopen(req, timeout=4))
        a = s.get("attributes", {})
        _sun.update(t=now, night=(s.get("state") == "below_horizon"),
                    set=a.get("next_setting"))
    except Exception as e:
        _log("sun.sun check failed (%s) -> allowing" % e)
        if _sun["night"] is None:            # never got a reading -> fail OPEN
            return {"t": now, "night": True, "set": None}
    return _sun

def _sunset_allows(c):
    # True if clap toggling is allowed under the sunset gate. Active window =
    # [sunset - pre_sunset_min, sunrise]. At night -> active (until sunrise, when
    # sun.sun flips to above_horizon). By day -> only within pre_sunset_min before
    # the next sunset. Fails OPEN if the sun state is unknown.
    s = _sun_state(c)
    if s["night"]:
        return True
    pre = float(c.get("pre_sunset_min", 0) or 0)
    if pre > 0 and s.get("set"):
        try:
            secs = (datetime.datetime.fromisoformat(s["set"])
                    - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            if 0 <= secs <= pre * 60:
                return True
        except Exception:
            pass
    return False


def _fire_toggle():
    # POST /api/services/<domain>/toggle for each configured entity
    c = _load_cfg()
    ents = _entities(c) if c else []
    if not c or not c.get("enabled") or not c.get("ha_token") or not ents:
        _log("double-clap (no HA config / disabled -> not toggling)")
        return
    if c.get("after_sunset") and not _sunset_allows(c):
        _log("double-clap ignored — outside the after-sunset window")
        return
    for e in ents:
        domain = e.split(".")[0]
        url = c["ha_url"].rstrip("/") + "/api/services/%s/toggle" % domain
        body = json.dumps({"entity_id": e}).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Authorization": "Bearer " + c["ha_token"],
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                _log("toggled %s -> HTTP %s" % (e, r.status))
        except Exception as ex:
            _log("toggle FAILED for %s: %s" % (e, ex))


def _tune(c):
    # returns (min_peak, ratio, boost, dbl_max, cooldown), honouring optional
    # advanced overrides (peak_abs / ratio) in clap.json
    boost = max(1.0, min(8.0, float(c.get("boost", 1.0))))
    min_peak, ratio = _sens_params(c.get("sensitivity", 6))
    t = c.get("tune", {})
    if "peak_abs" in c or "peak_abs" in t:
        min_peak = float(c.get("peak_abs", t.get("peak_abs")))
    if "ratio" in c or "ratio" in t:
        ratio = float(c.get("ratio", t.get("ratio")))
    dbl_max  = float(c.get("dbl_max",  t.get("dbl_max", 0.6)))
    cooldown = float(c.get("cooldown", t.get("cooldown", 1.2)))
    return min_peak, ratio, boost, dbl_max, cooldown


def _publish_stat(now, bg, sens, boost, min_peak, ratio, enabled):
    global _stat_t, _pk_hold
    if now - _stat_t < STAT_EVERY:
        return
    _stat_t = now
    try:
        st = {"t": now, "enabled": bool(enabled),
              "bg": round(bg / max(boost, 1e-6)), "peak": round(_pk_hold),
              "sens": sens, "boost": boost,
              "min_peak": round(min_peak / max(boost, 1e-6)), "ratio": round(ratio, 2),
              "singles": _singles, "doubles": _doubles,
              "last_single_ago": round(now - _last_edge, 1) if _last_edge else None,
              "last_double_ago": round(now - _last_double, 1) if _last_double else None}
        tmp = STAT_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, STAT_PATH)
    except Exception:
        pass
    _pk_hold = 0.0


def _on_edge(now, dbl_max, cooldown):
    # an accepted clap edge at time `now`; decide single vs double
    global _last_edge, _last_double, _muted_until, _singles, _doubles
    _singles += 1
    gap = now - _last_edge
    _last_edge = now
    if DBL_MIN <= gap <= dbl_max:
        _muted_until = now + cooldown
        _last_edge = 0.0            # consume the pair so a 3rd clap starts fresh
        _last_double = now
        _doubles += 1
        _log("DOUBLE CLAP (gap=%.0fms)" % (gap * 1000))
        threading.Thread(target=_fire_toggle, daemon=True).start()


def feed(mono):
    """Feed a 1-D int16 numpy array of mono samples. Never raises."""
    global _buf, _bg, _prev_pk, _pk_hold
    if _np is None:
        return
    try:
        c = _load_cfg() or {}
        min_peak, ratio, boost, dbl_max, cooldown = _tune(c)
        enabled = bool(c.get("enabled"))
        sens = c.get("sensitivity", 6)
        if mono is None or mono.size == 0:
            return
        raw = _buf + mono.astype("<i2").tobytes()
        n = len(raw) // (FRAME * 2)
        _buf = raw[n * FRAME * 2:]
        if n == 0:
            return
        frames = _np.frombuffer(raw[:n * FRAME * 2], dtype="<i2").reshape(n, FRAME)
        now = time.time()
        for fr in frames:
            raw_pk = float(_np.abs(fr).max())
            pk = raw_pk * boost
            now += FRAME / RATE
            if raw_pk > _pk_hold:
                _pk_hold = raw_pk
            # onset = a sharp RISE: the frame before must be much quieter than this
            # one. Relative (not an absolute floor) so it still fires in a loud room
            # yet rejects sustained loud noise (music/TV) where levels don't jump.
            quiet_before = _prev_pk < 0.5 * pk
            is_clap = (enabled and now >= _muted_until and quiet_before
                       and pk >= min_peak and pk >= ratio * _bg
                       and (now - _last_edge) >= REFRACTORY)
            if is_clap:
                _on_edge(now, dbl_max, cooldown)
            else:
                # only quiet frames update the background (claps mustn't inflate it)
                _bg = (1 - BG_ALPHA) * _bg + BG_ALPHA * min(pk, _bg * 3 + 200)
            _prev_pk = pk
            _publish_stat(now, _bg, sens, boost, min_peak, ratio, enabled)
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
