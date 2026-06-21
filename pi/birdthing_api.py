#!/usr/bin/env python3
# BirdThing dashboard API: serves recent BirdNET detections + bird photos for the
# Car Thing 800x480 screen. Reads BirdNET-Pi's SQLite DB; proxies/caches Wikipedia photos.
import sqlite3, os, json, urllib.request, urllib.parse, threading, time, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB = "/home/birdpi/BirdNET-Pi/scripts/birds.db"
HTML = "/opt/birdthing/birdthing-dashboard.html"
CACHE = "/opt/birdthing/imgcache"
WCONF = "/opt/birdthing/weather.json"
PORT = 8090
os.makedirs(CACHE, exist_ok=True)
_imglock = threading.Lock()

# WMO weather code -> (emoji icon, short description)
WMO = {0:("☀️","Clear"),1:("\U0001f324️","Mainly clear"),
 2:("⛅","Partly cloudy"),3:("☁️","Overcast"),
 45:("\U0001f32b️","Fog"),48:("\U0001f32b️","Rime fog"),
 51:("\U0001f326️","Light drizzle"),53:("\U0001f326️","Drizzle"),
 55:("\U0001f326️","Heavy drizzle"),56:("\U0001f327️","Freezing drizzle"),
 57:("\U0001f327️","Freezing drizzle"),61:("\U0001f327️","Light rain"),
 63:("\U0001f327️","Rain"),65:("\U0001f327️","Heavy rain"),
 66:("\U0001f327️","Freezing rain"),67:("\U0001f327️","Freezing rain"),
 71:("❄️","Light snow"),73:("❄️","Snow"),75:("❄️","Heavy snow"),
 77:("❄️","Snow grains"),80:("\U0001f326️","Showers"),
 81:("\U0001f327️","Showers"),82:("\U0001f327️","Heavy showers"),
 85:("\U0001f328️","Snow showers"),86:("\U0001f328️","Snow showers"),
 95:("⛈️","Thunderstorm"),96:("⛈️","Thunderstorm"),
 99:("⛈️","Thunderstorm")}

def load_wconf():
    c = {"lat": 44.6701, "lon": -74.9774, "unit": "C", "place": "Potsdam, NY"}
    try:
        c.update(json.load(open(WCONF)))
    except Exception:
        pass
    return c

def save_wconf(c):
    try:
        json.dump(c, open(WCONF, "w"))
    except Exception:
        pass

def weather():
    c = load_wconf()
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=temperature_2m,weather_code" % (c["lat"], c["lon"]))
        req = urllib.request.Request(url, headers={"User-Agent": "BirdThing/1.0"})
        cur = json.load(urllib.request.urlopen(req, timeout=8))["current"]
        tc = cur["temperature_2m"]; code = int(cur["weather_code"])
        temp = tc if c["unit"] == "C" else tc * 9 / 5 + 32
        icon, desc = WMO.get(code, ("\U0001f321️", "—"))
        return {"temp": round(temp), "unit": c["unit"], "icon": icon,
                "desc": desc, "place": c["place"]}
    except Exception as e:
        return {"temp": None, "unit": c["unit"], "icon": "\U0001f321️",
                "desc": "—", "place": c["place"], "err": str(e)}

def geocode(q):
    try:
        url = ("https://geocoding-api.open-meteo.com/v1/search?name=%s&count=5"
               % urllib.parse.quote(q))
        req = urllib.request.Request(url, headers={"User-Agent": "BirdThing/1.0"})
        res = json.load(urllib.request.urlopen(req, timeout=8)).get("results", [])
        out = []
        for r in res:
            place = r["name"]
            if r.get("admin1"): place += ", " + r["admin1"]
            if r.get("country_code"): place += ", " + r["country_code"]
            out.append({"place": place, "lat": r["latitude"], "lon": r["longitude"]})
        return out
    except Exception:
        return []

def _read_level():
    # Current loudness the mic is hearing (written by the receiver). Used for a real-time
    # "hearing a bird" indicator that reacts to sound, not to the (slower) BirdNET ID.
    try:
        return int(open("/tmp/bt_level").read().strip() or 0)
    except Exception:
        return 0


def tz_off_min():
    # Pi local UTC offset in minutes east of UTC (e.g. EDT = -240). The Car Thing
    # has no RTC/NTP and a wrong clock+TZ, so the dashboard renders time from this.
    is_dst = time.localtime().tm_isdst > 0
    secs_west = time.altzone if is_dst else time.timezone
    return -secs_west // 60


def detections(limit=60):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
        cur = con.execute(
            "SELECT Date,Time,Com_Name,Sci_Name,Confidence FROM detections "
            "ORDER BY Date DESC, Time DESC LIMIT ?", (limit,))
        rows = [{"date": r[0], "time": r[1], "com": r[2], "sci": r[3],
                 "conf": round(r[4], 2)} for r in cur.fetchall()]
        today = con.execute(
            "SELECT COUNT(*) , COUNT(DISTINCT Com_Name) FROM detections WHERE Date=?",
            (rows[0]["date"],)).fetchone() if rows else (0, 0)
        con.close()
        return {"rows": rows, "today_count": today[0], "today_species": today[1],
                "now": int(time.time() * 1000), "tzoff": tz_off_min(), "level": _read_level()}
    except Exception as e:
        return {"rows": [], "today_count": 0, "today_species": 0, "err": str(e),
                "now": int(time.time() * 1000), "tzoff": tz_off_min(), "level": _read_level()}

def by_date(days=7):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
        cur = con.execute(
            "SELECT Date,Com_Name,Sci_Name,COUNT(*) c FROM detections "
            "GROUP BY Date,Com_Name ORDER BY Date DESC, c DESC")
        out = []
        for date, com, sci, c in cur.fetchall():
            day = next((d for d in out if d["date"] == date), None)
            if not day:
                if len(out) >= days:
                    continue
                day = {"date": date, "birds": []}; out.append(day)
            day["birds"].append({"com": com, "sci": sci, "count": c})
        con.close()
        return out
    except Exception as e:
        return []

def stats():
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
        today = con.execute("SELECT MAX(Date) FROM detections").fetchone()[0]
        hourly = [0] * 24
        for hr, c in con.execute(
                "SELECT CAST(substr(Time,1,2) AS INT) h,COUNT(*) FROM detections "
                "WHERE Date=? GROUP BY h", (today,)):
            if 0 <= hr < 24:
                hourly[hr] = c
        top = [{"com": r[0], "count": r[1]} for r in con.execute(
            "SELECT Com_Name,COUNT(*) c FROM detections WHERE Date=? "
            "GROUP BY Com_Name ORDER BY c DESC LIMIT 5", (today,))]
        total = con.execute("SELECT COUNT(*) FROM detections WHERE Date=?", (today,)).fetchone()[0]
        species = con.execute("SELECT COUNT(DISTINCT Com_Name) FROM detections WHERE Date=?", (today,)).fetchone()[0]
        alltime = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        con.close()
        return {"hourly": hourly, "top": top, "total": total, "species": species, "alltime": alltime}
    except Exception as e:
        return {"hourly": [0]*24, "top": [], "total": 0, "species": 0, "alltime": 0}

XCKEY_FILE = "/opt/birdthing/xenocanto.key"

def _xckey():
    try:
        return open(XCKEY_FILE).read().strip()
    except Exception:
        return os.environ.get("XC_KEY", "").strip()

def song(name):
    # Find a bird-call recording via the Xeno-canto API v3 (needs a free API key, since Oct 2025).
    # Put the key in /opt/birdthing/xenocanto.key (get it at https://xeno-canto.org/account).
    key = _xckey()
    if not key:
        return {"url": "", "err": "no-key"}
    try:
        url = ("https://xeno-canto.org/api/3/recordings?query=" +
               urllib.parse.quote(name) + "&key=" + urllib.parse.quote(key))
        req = urllib.request.Request(url, headers={"User-Agent": "BirdThing/1.0"})
        recs = json.load(urllib.request.urlopen(req, timeout=8)).get("recordings", [])
        for r in recs:
            f = r.get("file")
            if f:
                if f.startswith("//"):
                    f = "https:" + f
                return {"url": f}
        return {"url": ""}
    except Exception as e:
        return {"url": "", "err": str(e)}


BNCONF = "/home/birdpi/BirdNET-Pi/birdnet.conf"

def _set_conf(kv):
    try:
        lines = open(BNCONF).read().splitlines()
        seen = set()
        for i, l in enumerate(lines):
            for k, v in kv.items():
                if l.startswith(k + "="):
                    lines[i] = "%s=%s" % (k, v); seen.add(k)
        for k, v in kv.items():
            if k not in seen:
                lines.append("%s=%s" % (k, v))
        open(BNCONF, "w").write("\n".join(lines) + "\n")
        subprocess.run(["sudo", "systemctl", "restart", "birdnet_analysis"], capture_output=True)
        return True
    except Exception:
        return False

def birdloc(lat, lon, place):
    try:
        kv = {"LATITUDE": "%.4f" % float(lat), "LONGITUDE": "%.4f" % float(lon)}
    except Exception:
        return {"ok": False, "err": "bad coords"}
    ok = _set_conf(kv)
    if place:
        try:
            json.dump({"place": place}, open(BIRDLOC_FILE, "w"))
        except Exception:
            pass
    return {"ok": ok, "lat": kv["LATITUDE"], "lon": kv["LONGITUDE"], "place": place}

def set_sf(thresh):
    try:
        t = max(0.0, min(0.1, float(thresh)))
    except Exception:
        return {"ok": False}
    return {"ok": _set_conf({"SF_THRESH": "%.3f" % t}), "sf": t}

def geoip():
    try:
        r = json.load(urllib.request.urlopen(
            "http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country", timeout=8))
        if r.get("status") != "success":
            return {"err": "lookup failed"}
        place = ", ".join(x for x in [r.get("city"), r.get("regionName"), r.get("country")] if x)
        return {"lat": r.get("lat"), "lon": r.get("lon"), "place": place}
    except Exception as e:
        return {"err": str(e)}

BIRDLOC_FILE = "/opt/birdthing/birdloc.json"

def _nm_unesc(s):
    return s.replace("\\:", ":").replace("\\\\", "\\")

def wifi_status():
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
                             capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if line.startswith("yes:"):
                return {"ssid": _nm_unesc(line[4:])}
        return {"ssid": ""}
    except Exception as e:
        return {"ssid": "", "err": str(e)}

def wifi_scan():
    try:
        # Trigger a rescan, then WAIT for the full multi-channel scan to finish before listing.
        # (--rescan yes / immediate list return only the connected AP because the scan, while
        # associated, hasn't swept all channels yet. rescan + ~5s settle finds every nearby network.)
        subprocess.run(["nmcli", "dev", "wifi", "rescan"], capture_output=True, timeout=15)
        time.sleep(5)
        out = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
                             capture_output=True, text=True, timeout=15).stdout
        best = {}
        for line in out.splitlines():
            p = line.replace("\\:", "\x00").split(":")
            if len(p) < 2:
                continue
            ssid = p[0].replace("\x00", ":")
            if not ssid:
                continue
            try:
                sig = int(p[1])
            except Exception:
                sig = 0
            sec = len(p) > 2 and p[2] not in ("", "--")
            if ssid not in best or sig > best[ssid]["signal"]:
                best[ssid] = {"ssid": ssid, "signal": sig, "secure": sec}
        return sorted(best.values(), key=lambda x: -x["signal"])[:30]
    except Exception as e:
        return []

def wifi_connect(ssid, psk):
    try:
        cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid]
        if psk:
            cmd += ["password", psk]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        return {"ok": r.returncode == 0, "msg": (r.stdout or r.stderr).strip()[:160]}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def analytics():
    # Live "today" analytics for the on-screen view: volume, species, and a confidence-based
    # quality proxy (high-confidence vs borderline = likely-false).
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
        today = con.execute("SELECT MAX(Date) FROM detections").fetchone()[0]
        rows = con.execute("SELECT Com_Name,Confidence,Time FROM detections WHERE Date=?",
                           (today,)).fetchall()
        con.close()
        if not rows:
            return {"date": today, "detections": 0, "species": 0}
        confs = [r[1] for r in rows]
        sp = {}
        for com, cf, _ in rows:
            sp.setdefault(com, []).append(cf)
        hourly = [0] * 24
        for _, _, t in rows:
            try:
                hourly[int(t[:2])] += 1
            except Exception:
                pass
        hi = sum(1 for c in confs if c >= 0.85)
        bord = sum(1 for c in confs if 0.70 <= c < 0.80)
        top = sorted(([k, len(v), round(sum(v) / len(v), 2)] for k, v in sp.items()),
                     key=lambda x: -x[1])[:8]
        return {"date": today, "detections": len(rows), "species": len(sp),
                "conf_mean": round(sum(confs) / len(confs), 2),
                "high_pct": round(100 * hi / len(confs)),
                "bord_pct": round(100 * bord / len(confs)),
                "hourly": hourly, "peak": hourly.index(max(hourly)), "top": top}
    except Exception as e:
        return {"date": "", "detections": 0, "species": 0, "err": str(e)}


def play_pi(name):
    # Play the bird's call on the PI's default audio sink (e.g. a paired Bluetooth speaker).
    s = song(name)
    if not s.get("url"):
        return {"ok": False, "err": s.get("err", "no-recording")}
    try:
        subprocess.run(["pkill", "-f", "mpg123"], capture_output=True)
        subprocess.Popen(["mpg123", "-q", s["url"]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}
    except FileNotFoundError:
        return {"ok": False, "err": "mpg123-not-installed"}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def stop_pi():
    try:
        subprocess.run(["pkill", "-f", "mpg123"], capture_output=True)
    except Exception:
        pass
    return {"ok": True}


def fetch_info(name):
    safe = "".join(c for c in name if c.isalnum() or c in " -").strip()
    path = os.path.join(CACHE, safe + ".json")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            return json.load(open(path))
        except Exception:
            pass
    try:
        api = ("https://en.wikipedia.org/api/rest_v1/page/summary/" +
               urllib.parse.quote(name.replace(" ", "_")))
        req = urllib.request.Request(api, headers={"User-Agent": "BirdThing/1.0"})
        meta = json.load(urllib.request.urlopen(req, timeout=8))
        out = {"extract": meta.get("extract", ""),
               "title": meta.get("title", name)}
        with open(path, "w") as f:
            json.dump(out, f)
        return out
    except Exception as e:
        return {"extract": "", "title": name, "err": str(e)}

def _is_img(data):
    # a real JPEG or PNG, big enough to be a photo (not an error page / partial download)
    return bool(data) and len(data) > 1024 and (
        data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n")

def _valid_cached(path):
    try:
        if os.path.getsize(path) < 1024:
            return False
        with open(path, "rb") as f:
            return _is_img(f.read(16) + b" " * 1024)  # magic check only
    except Exception:
        return False

def fetch_image(name):
    safe = "".join(c for c in name if c.isalnum() or c in " -").strip()
    path = os.path.join(CACHE, safe + ".jpg")
    if _valid_cached(path):
        return path
    with _imglock:
        if _valid_cached(path):
            return path
        try:
            api = ("https://en.wikipedia.org/api/rest_v1/page/summary/" +
                   urllib.parse.quote(name.replace(" ", "_")))
            req = urllib.request.Request(api, headers={"User-Agent": "BirdThing/1.0"})
            meta = json.load(urllib.request.urlopen(req, timeout=8))
            url = meta.get("thumbnail", {}).get("source") or \
                  meta.get("originalimage", {}).get("source")
            if url:
                req2 = urllib.request.Request(url, headers={"User-Agent": "BirdThing/1.0"})
                data = urllib.request.urlopen(req2, timeout=8).read()
                if _is_img(data):                 # only cache a genuine image -> broken fetches retry
                    with open(path, "wb") as f:
                        f.write(data)
                    return path
        except Exception:
            pass
    return None

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, ctype, body):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            try:
                with open(HTML, "rb") as f: body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Cache-Control", "no-store, must-revalidate")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
            except Exception as e:
                self._send(500, "text/plain", str(e).encode())
        elif self.path.startswith("/api/detections"):
            self._send(200, "application/json", json.dumps(detections()).encode())
        elif self.path.startswith("/api/bydate"):
            self._send(200, "application/json", json.dumps(by_date()).encode())
        elif self.path.startswith("/api/stats"):
            self._send(200, "application/json", json.dumps(stats()).encode())
        elif self.path.startswith("/api/song"):
            q = urllib.parse.urlparse(self.path).query
            name = urllib.parse.parse_qs(q).get("name", [""])[0]
            self._send(200, "application/json", json.dumps(song(name)).encode())
        elif self.path.startswith("/api/geoip"):
            self._send(200, "application/json", json.dumps(geoip()).encode())
        elif self.path.startswith("/api/birdloc"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send(200, "application/json", json.dumps(birdloc(
                q.get("lat", ["0"])[0], q.get("lon", ["0"])[0], q.get("place", [""])[0])).encode())
        elif self.path.startswith("/api/sf"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send(200, "application/json", json.dumps(set_sf(q.get("t", ["0.03"])[0])).encode())
        elif self.path.startswith("/api/wifi/scan"):
            self._send(200, "application/json", json.dumps(wifi_scan()).encode())
        elif self.path.startswith("/api/wifi/connect"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send(200, "application/json", json.dumps(
                wifi_connect(q.get("ssid", [""])[0], q.get("psk", [""])[0])).encode())
        elif self.path.startswith("/api/wifi"):
            self._send(200, "application/json", json.dumps(wifi_status()).encode())
        elif self.path.startswith("/api/analytics"):
            self._send(200, "application/json", json.dumps(analytics()).encode())
        elif self.path.startswith("/api/play_pi"):
            q = urllib.parse.urlparse(self.path).query
            name = urllib.parse.parse_qs(q).get("name", [""])[0]
            self._send(200, "application/json", json.dumps(play_pi(name)).encode())
        elif self.path.startswith("/api/stop_pi"):
            self._send(200, "application/json", json.dumps(stop_pi()).encode())
        elif self.path.startswith("/api/info"):
            q = urllib.parse.urlparse(self.path).query
            name = urllib.parse.parse_qs(q).get("name", [""])[0]
            self._send(200, "application/json", json.dumps(fetch_info(name)).encode())
        elif self.path.startswith("/api/weather/unit"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            c = load_wconf(); c["unit"] = "F" if q.get("u", ["C"])[0].upper() == "F" else "C"
            save_wconf(c)
            self._send(200, "application/json", json.dumps(weather()).encode())
        elif self.path.startswith("/api/weather/loc"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            c = load_wconf()
            try:
                c["lat"] = float(q["lat"][0]); c["lon"] = float(q["lon"][0])
                c["place"] = q.get("place", [c["place"]])[0]; save_wconf(c)
            except Exception:
                pass
            self._send(200, "application/json", json.dumps(weather()).encode())
        elif self.path.startswith("/api/weather"):
            self._send(200, "application/json", json.dumps(weather()).encode())
        elif self.path.startswith("/api/geocode"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send(200, "application/json",
                       json.dumps(geocode(q.get("q", [""])[0])).encode())
        elif self.path.startswith("/assets/"):
            fn = os.path.basename(urllib.parse.urlparse(self.path).path)
            fp = os.path.join("/opt/birdthing/assets", fn)
            if os.path.exists(fp) and "/" not in fn.replace("..", ""):
                ct = "font/woff2" if fn.endswith(".woff2") else "application/octet-stream"
                with open(fp, "rb") as f:
                    self.send_response(200); self.send_header("Content-Type", ct)
                    self.send_header("Cache-Control", "max-age=86400")
                    body = f.read(); self.send_header("Content-Length", str(len(body)))
                    self.end_headers(); self.wfile.write(body)
            else:
                self._send(404, "text/plain", b"no asset")
        elif self.path.startswith("/api/image"):
            q = urllib.parse.urlparse(self.path).query
            name = urllib.parse.parse_qs(q).get("name", [""])[0]
            p = fetch_image(name) if name else None
            if p:
                with open(p, "rb") as f: self._send(200, "image/jpeg", f.read())
            else:
                self._send(404, "text/plain", b"no image")
        else:
            self._send(404, "text/plain", b"not found")

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
