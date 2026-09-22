import { BridgethingClient, type ConnectionState, type Notification, type Peer, type TimeInfo } from '@bridgething/client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { daemonUrl } from './daemon';

type Unit = 'C' | 'F';

const WMO: Record<number, [string, string]> = {
  0: ['clear', 'Clear'],
  1: ['mclear', 'Mainly clear'],
  2: ['partly', 'Partly cloudy'],
  3: ['cloud', 'Overcast'],
  45: ['fog', 'Fog'],
  48: ['fog', 'Rime fog'],
  51: ['drizzle', 'Light drizzle'],
  53: ['drizzle', 'Drizzle'],
  55: ['drizzle', 'Heavy drizzle'],
  56: ['drizzle', 'Freezing drizzle'],
  57: ['drizzle', 'Freezing drizzle'],
  61: ['rain', 'Light rain'],
  63: ['rain', 'Rain'],
  65: ['rain', 'Heavy rain'],
  66: ['rain', 'Freezing rain'],
  67: ['rain', 'Freezing rain'],
  71: ['snow', 'Light snow'],
  73: ['snow', 'Snow'],
  75: ['snow', 'Heavy snow'],
  77: ['snow', 'Snow grains'],
  80: ['rain', 'Showers'],
  81: ['rain', 'Showers'],
  82: ['rain', 'Heavy showers'],
  85: ['snow', 'Snow showers'],
  86: ['snow', 'Snow showers'],
  95: ['storm', 'Thunderstorm'],
  96: ['storm', 'Thunderstorm'],
  99: ['storm', 'Thunderstorm'],
};
const wmo = (code: number): [string, string] => WMO[code] ?? ['cloud', '—'];

const SUN = '#ffd60a';
const CL = '#dfe4ec';
const CLN = '#aeb6c2';
const DROP = '#4aa8ff';
const FLAKE = '#ffffff';
const BOLT = '#ffd60a';
const MOONC = '#e6ebf7';

function WeatherIcon({ icon, night, className }: { icon: string; night?: boolean; className?: string }) {
  const key = night && (icon === 'clear' || icon === 'mclear') ? 'moon' : icon;
  const svgProps = { viewBox: '0 0 24 24', className, fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  switch (key) {
    case 'clear':
    case 'mclear':
      return (
        <svg {...svgProps}>
          <g stroke={SUN} strokeWidth="1.8">
            <path d="M12 2.4v2.3M12 19.3v2.3M4.4 4.4 6 6M18 18l1.6 1.6M2.4 12h2.3M19.3 12h2.3M4.4 19.6 6 18M18 6l1.6-1.6" />
          </g>
          <circle cx="12" cy="12" r="4.4" fill={SUN} stroke={SUN} strokeWidth="1.8" />
        </svg>
      );
    case 'moon':
      return (
        <svg {...svgProps}>
          <path d="M20 14.3A8 8 0 0 1 9.7 4 8 8 0 1 0 20 14.3Z" fill={MOONC} stroke={MOONC} strokeWidth="1.4" />
        </svg>
      );
    case 'partly':
      return (
        <svg {...svgProps}>
          <g stroke={SUN} strokeWidth="1.6">
            <path d="M7.5 2.4v1.7M2.5 7.5h1.7M3.6 3.6 4.8 4.8M12.5 7.5h-1.7M11.4 3.6 10.2 4.8" />
          </g>
          <circle cx="7.5" cy="7.5" r="2.9" fill={SUN} stroke={SUN} strokeWidth="1.6" />
          <path
            d="M17.5 20H8.2a4.4 4.4 0 1 1 .9-8.7A5.4 5.4 0 0 1 20 13.4 3.2 3.2 0 0 1 17.5 20Z"
            fill={CL}
            stroke={CLN}
            strokeWidth="1.2"
          />
        </svg>
      );
    case 'fog':
      return (
        <svg {...svgProps}>
          <path
            d="M17.5 13.5H8a5.3 5.3 0 1 1 1.1-10.5A6.3 6.3 0 0 1 20.3 5.6 3.6 3.6 0 0 1 17.5 13.5Z"
            fill={CL}
            stroke={CLN}
            strokeWidth="1.2"
          />
          <g stroke={CLN} strokeWidth="1.8">
            <path d="M5 17.5h11M7 20.5h8" />
          </g>
        </svg>
      );
    case 'drizzle':
      return (
        <svg {...svgProps}>
          <path
            d="M17.5 14.5H8a5.3 5.3 0 1 1 1.1-10.5A6.3 6.3 0 0 1 20.3 6.6 3.6 3.6 0 0 1 17.5 14.5Z"
            fill={CL}
            stroke={CLN}
            strokeWidth="1.2"
          />
          <g stroke={DROP} strokeWidth="2">
            <path d="M9 18v1.6M13 18v1.6M17 18v1.6" />
          </g>
        </svg>
      );
    case 'rain':
      return (
        <svg {...svgProps}>
          <path
            d="M17.5 14H8a5.3 5.3 0 1 1 1.1-10.5A6.3 6.3 0 0 1 20.3 6.1 3.6 3.6 0 0 1 17.5 14Z"
            fill={CL}
            stroke={CLN}
            strokeWidth="1.2"
          />
          <g stroke={DROP} strokeWidth="2">
            <path d="M9 17.5v3M13 17.5v3M17 17.5v3" />
          </g>
        </svg>
      );
    case 'snow':
      return (
        <svg {...svgProps}>
          <path
            d="M17.5 14H8a5.3 5.3 0 1 1 1.1-10.5A6.3 6.3 0 0 1 20.3 6.1 3.6 3.6 0 0 1 17.5 14Z"
            fill={CL}
            stroke={CLN}
            strokeWidth="1.2"
          />
          <g stroke={FLAKE} strokeWidth="2.2">
            <path d="M9 18h.01M9 20.6h.01M13 18.7h.01M13 21.3h.01M17 18h.01M17 20.6h.01" />
          </g>
        </svg>
      );
    case 'storm':
      return (
        <svg {...svgProps}>
          <path
            d="M17.5 13.5H8a5.3 5.3 0 1 1 1.1-10.5A6.3 6.3 0 0 1 20.3 5.6 3.6 3.6 0 0 1 17.5 13.5Z"
            fill={CLN}
            stroke="#97a0ad"
            strokeWidth="1.2"
          />
          <path d="M12.5 12.5 10.2 16.5h3l-2.3 4" fill="none" stroke={BOLT} strokeWidth="2" />
        </svg>
      );
    default:
      return (
        <svg {...svgProps}>
          <path
            d="M17.5 18.5H8a5.3 5.3 0 1 1 1.1-10.5A6.3 6.3 0 0 1 20.3 10.6 3.6 3.6 0 0 1 17.5 18.5Z"
            fill={CL}
            stroke={CLN}
            strokeWidth="1.2"
          />
        </svg>
      );
  }
}

const FDAY = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const FMON = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

type Hour = { t: string; temp: number; icon: string };
type Day = { date: string; dow: string; icon: string; hi: number; lo: number };
type Weather = {
  temp: number;
  desc: string;
  icon: string;
  hi: number;
  lo: number;
  hourly: Hour[];
  daily: Day[];
  sunrise: string | null;
  sunset: string | null;
};

const DOW_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function BluetoothGlyph({ status }: { status: 'connected' | 'paired' | 'none' }) {
  const color = status === 'connected' ? '#54c7ff' : status === 'paired' ? '#ffd60a' : 'var(--color-dim)';
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill={color}>
      <path d="M13 5.83 14.88 7.7 13 9.59V5.83M13 14.41l1.88 1.88L13 18.17v-3.76M17.71 7.71 12 2h-1v7.59L6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 11 14.41V22h1l5.71-5.71-4.3-4.29 4.3-4.29Z" />
    </svg>
  );
}

type GeocodeResult = { ok: true; lat: number; lon: number } | { ok: false; reason: string };

async function geocodePlace(client: BridgethingClient, place: string): Promise<GeocodeResult> {
  if (!place.trim()) return { ok: false, reason: 'empty' };
  const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(place)}&count=1&language=en&format=json`;
  try {
    const res = await client.net.fetch({
      request: { url, method: 'GET', headers: [], body: null, timeoutMs: 8000, redirect: 'follow' },
    });
    if (!res.ok) {
      const reason = res.kind === 'domain' ? res.error.error.type : res.error.type;
      return { ok: false, reason };
    }
    const { status, body } = res.response.response;
    if (status < 200 || status >= 300) return { ok: false, reason: `http ${status}` };
    const bytes = new Uint8Array(body as unknown as number[]);
    const d = JSON.parse(new TextDecoder().decode(bytes));
    const r = d.results?.[0];
    if (!r) return { ok: false, reason: 'not found' };
    return { ok: true, lat: r.latitude, lon: r.longitude };
  } catch (err) {
    return { ok: false, reason: err instanceof Error ? err.message : String(err) };
  }
}

async function fetchWeather(client: BridgethingClient, lat: number, lon: number, unit: Unit): Promise<Weather> {
  const imperial = unit === 'F';
  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
    `&current=temperature_2m,weather_code` +
    `&hourly=temperature_2m,weather_code` +
    `&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset` +
    `&forecast_days=7&timezone=auto` +
    `&temperature_unit=${imperial ? 'fahrenheit' : 'celsius'}`;
  const res = await client.net.fetch({
    request: { url, method: 'GET', headers: [], body: null, timeoutMs: 8000, redirect: 'follow' },
  });
  if (!res.ok) {
    const reason = res.kind === 'domain' ? res.error.error.type : res.error.type;
    throw new Error(reason);
  }
  const { status, body } = res.response.response;
  if (status < 200 || status >= 300) throw new Error(`http ${status}`);
  const bytes = new Uint8Array(body as unknown as number[]);
  const d = JSON.parse(new TextDecoder().decode(bytes));

  const cur = d.current;
  const [icon, desc] = wmo(cur.weather_code);
  const H = d.hourly;
  const nowIso = (cur.time as string).slice(0, 13);
  let start = (H.time as string[]).findIndex(t => t.slice(0, 13) >= nowIso);
  if (start < 0) start = 0;
  const hourly: Hour[] = [];
  for (let i = start; i < Math.min(start + 7, H.time.length); i++) {
    hourly.push({ t: H.time[i].slice(11, 16), temp: Math.round(H.temperature_2m[i]), icon: wmo(H.weather_code[i])[0] });
  }
  const DD = d.daily;
  const daily: Day[] = (DD.time as string[]).map((date, i) => {
    const [y, mo, da] = date.split('-').map(Number);
    const dow = DOW_SHORT[new Date(Date.UTC(y, mo - 1, da)).getUTCDay()];
    return { date, dow, icon: wmo(DD.weather_code[i])[0], hi: Math.round(DD.temperature_2m_max[i]), lo: Math.round(DD.temperature_2m_min[i]) };
  });

  return {
    temp: Math.round(cur.temperature_2m),
    desc,
    icon,
    hi: Math.round(DD.temperature_2m_max[0]),
    lo: Math.round(DD.temperature_2m_min[0]),
    hourly,
    daily,
    sunrise: DD.sunrise?.[0]?.slice(11, 16) ?? null,
    sunset: DD.sunset?.[0]?.slice(11, 16) ?? null,
  };
}

function hr12(t: string): string {
  const [h] = t.split(':').map(Number);
  const ap = h < 12 ? 'a' : 'p';
  const hh = h % 12 || 12;
  return `${hh}${ap}`;
}

function hm(s: string | null): number | null {
  if (!s) return null;
  const [h, m] = s.split(':').map(Number);
  return h * 60 + m;
}

// Embedded Chromium builds often ship without full ICU timezone data, so
// Intl/toLocaleString with a `timeZone` option can throw and crash the render.
// Shift the epoch by the daemon's plain numeric offset instead, then read the
// wall clock back out with the UTC getters -- no Intl involved at all.
//
// `driftMs` must be captured ONCE per `time` update (the gap between the daemon's clock and
// Date.now() at that instant) and then added to a FRESH Date.now() on every tick. Computing
// drift from Date.now() and immediately adding it back to another Date.now() in the same
// expression cancels both calls out algebraically, freezing the result at a single instant
// forever -- which is exactly the bug that shipped: the clock and analog hands never moved.
function driftMsFor(time: TimeInfo | null): number {
  return time?.wallClockUnixS ? time.wallClockUnixS * 1000 - Date.now() : 0;
}
function offsetMinFor(time: TimeInfo | null): number {
  return (time?.utcOffsetMinutes ?? -new Date().getTimezoneOffset()) + (time?.dstOffsetMinutes ?? 0);
}
function localNow(driftMs: number, offsetMin: number): Date {
  return new Date(Date.now() + driftMs + offsetMin * 60000);
}

// clock ticks: 60 lines, every 5th longer and brighter, matching the real weatherstation dial.
const TICKS = Array.from({ length: 60 }, (_, i) => {
  const a = (i * 6 * Math.PI) / 180;
  const big = i % 5 === 0;
  const r1 = big ? 85 : 89;
  const r2 = 97;
  return {
    x1: (100 + r1 * Math.sin(a)).toFixed(1),
    y1: (100 - r1 * Math.cos(a)).toFixed(1),
    x2: (100 + r2 * Math.sin(a)).toFixed(1),
    y2: (100 - r2 * Math.cos(a)).toFixed(1),
    big,
  };
});

type Theme = 'auto' | 'dark' | 'light';

// on-device location picker: coordinates are baked in so it works instantly with no network
// round trip, as a companion to the companion app's free-text (geocoded) place field.
const PRESET_PLACES: { name: string; lat: number; lon: number }[] = [
  { name: 'New York, NY', lat: 40.7128, lon: -74.006 },
  { name: 'Los Angeles, CA', lat: 34.0522, lon: -118.2437 },
  { name: 'Chicago, IL', lat: 41.8781, lon: -87.6298 },
  { name: 'Houston, TX', lat: 29.7604, lon: -95.3698 },
  { name: 'Phoenix, AZ', lat: 33.4484, lon: -112.074 },
  { name: 'Seattle, WA', lat: 47.6062, lon: -122.3321 },
  { name: 'Denver, CO', lat: 39.7392, lon: -104.9903 },
  { name: 'Miami, FL', lat: 25.7617, lon: -80.1918 },
  { name: 'Boston, MA', lat: 42.3601, lon: -71.0589 },
  { name: 'Minneapolis, MN', lat: 44.9778, lon: -93.265 },
  { name: 'London, UK', lat: 51.5074, lon: -0.1278 },
  { name: 'Toronto, Canada', lat: 43.6532, lon: -79.3832 },
];

type Mode = 'home' | 'settings' | 'forecast' | 'standby' | 'notifications';

export default function App() {
  const client = useMemo(() => new BridgethingClient({ url: daemonUrl() }), []);
  const [conn, setConn] = useState<ConnectionState>(client.connectionState);
  const [time, setTime] = useState<TimeInfo | null>(null);
  const [place, setPlace] = useState('New York, NY');
  const [fallbackLat, setFallbackLat] = useState(40.7128);
  const [fallbackLon, setFallbackLon] = useState(-74.006);
  const [geocoded, setGeocoded] = useState<{ lat: number; lon: number } | null>(null);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [configUnit, setConfigUnit] = useState<Unit>('C');
  const [unitOverride, setUnitOverride] = useState<Unit | null>(null);
  const [themeConfig, setThemeConfig] = useState<Theme>('auto');
  const [themeOverride, setThemeOverride] = useState<'dark' | 'light' | null>(null);
  const [weather, setWeather] = useState<Weather | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [presetIndex, setPresetIndex] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>('home');
  const [peers, setPeers] = useState<Peer[]>([]);
  const [pressed, setPressed] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [refreshFlash, setRefreshFlash] = useState(false);

  useEffect(() => {
    const off = client.peer.onSnapshot(map => setPeers(Object.values(map)));
    return off;
  }, [client]);

  // a peer can show companion.type 'connected' from Bluetooth pairing alone, with the actual
  // companion APP not running on the phone -- capabilities is the true "is anything usable right
  // now" signal, so require both before calling it fully connected.
  const [capsReady, setCapsReady] = useState(false);
  useEffect(() => {
    client.capabilities
      .get()
      .then(r => r.ok && setCapsReady(r.response.capabilities.available.netFetch || r.response.capabilities.available.notifications))
      .catch(() => {});
    const off = client.capabilities.onSnapshot(c => setCapsReady(c.capabilities.available.netFetch || c.capabilities.available.notifications));
    return off;
  }, [client]);

  // only ever holds notifications posted while this app has been running -- there is no
  // "list what's already on the phone" request in the SDK, only live post/update/remove events.
  useEffect(() => {
    const offPosted = client.notifications.onPosted(n => setNotifications(prev => [n, ...prev.filter(p => p.id !== n.id)]));
    const offUpdated = client.notifications.onUpdated(n => setNotifications(prev => prev.map(p => (p.id === n.id ? n : p))));
    const offRemoved = client.notifications.onRemoved(({ id }) => setNotifications(prev => prev.filter(p => p.id !== id)));
    return () => {
      offPosted();
      offUpdated();
      offRemoved();
    };
  }, [client]);

  const phonePeer = peers.find(p => p.device.type === 'android' || p.device.type === 'iOS') ?? null;
  const phoneStatus: 'connected' | 'paired' | 'none' =
    phonePeer?.companion.type === 'connected' && capsReady ? 'connected' : phonePeer ? 'paired' : 'none';

  const unit = unitOverride ?? configUnit;
  const preset = presetIndex != null ? PRESET_PLACES[presetIndex] : null;
  const lat = preset?.lat ?? geocoded?.lat ?? fallbackLat;
  const lon = preset?.lon ?? geocoded?.lon ?? fallbackLon;
  const placeLabel = preset?.name ?? place;

  // an on-device location pick (mode button + wheel) persists locally across restarts as a
  // convenience, but a real place typed into the companion app always wins: see the
  // client.config.onChanged handler below, which clears this the moment `place` actually changes.
  useEffect(() => {
    client.store
      .get({ key: 'presetPlaceIndex' })
      .then(r => {
        if (r.ok && r.response.value) setPresetIndex(Number(r.response.value));
      })
      .catch(() => {});
  }, [client]);
  useEffect(() => {
    if (presetIndex == null) {
      client.store.delete({ key: 'presetPlaceIndex' }).catch(() => {});
      return;
    }
    client.store.put({ key: 'presetPlaceIndex', value: String(presetIndex) }).catch(() => {});
  }, [client, presetIndex]);

  useEffect(() => {
    const off = client.on(event => {
      if (event.type === 'open' || event.type === 'close' || event.type === 'connecting') {
        setConn(client.connectionState);
      }
    });
    client.time
      .get()
      .then(r => r.ok && setTime(r.response.time))
      .catch(() => {});
    const offTime = client.time.onChanged(t => setTime(t.time));

    const applyConfig = (key: string, value: string | null) => {
      if (value == null) return;
      if (key === 'place') setPlace(value);
      if (key === 'lat') setFallbackLat(Number(value));
      if (key === 'lon') setFallbackLon(Number(value));
      if (key === 'unit') setConfigUnit(value === 'F' ? 'F' : 'C');
      if (key === 'theme') setThemeConfig(value === 'dark' || value === 'light' ? value : 'auto');
    };
    Promise.all(
      ['place', 'lat', 'lon', 'unit', 'theme'].map(key =>
        client.config.get({ key }).then(r => r.ok && applyConfig(key, r.response.value)),
      ),
    ).catch(() => {});
    // onChanged only fires on a REAL edit (not the initial hydration above), so this is exactly
    // the signal that the companion app just set a new place -- clear the on-device preset so
    // the typed location takes over immediately instead of being silently overridden by it.
    const offConfig = client.config.onChanged(c => {
      if (c.key === 'place') setPresetIndex(null);
      applyConfig(c.key, c.value);
    });

    return () => {
      off();
      offTime();
      offConfig();
    };
  }, [client]);

  // resolve the typed place name to coordinates; falls back to the manual lat/lon config on failure.
  useEffect(() => {
    if (preset) return; // an on-device pick already has coordinates, no geocoding needed
    let cancelled = false;
    setGeoError(null);
    geocodePlace(client, place).then(r => {
      if (cancelled) return;
      if (r.ok) setGeocoded({ lat: r.lat, lon: r.lon });
      else setGeoError(r.reason === 'not found' ? `couldn't find "${place}"` : `location lookup failed: ${r.reason}`);
    });
    return () => {
      cancelled = true;
    };
  }, [client, place, preset]);

  const refresh = useMemo(
    () => async () => {
      try {
        setWeather(await fetchWeather(client, lat, lon, unit));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [client, lat, lon, unit],
  );

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, error ? 30 * 1000 : 3 * 60 * 1000);
    return () => clearInterval(id);
  }, [refresh, error]);

  // wall-clock: shift the epoch by the daemon's numeric UTC+DST offset (not Intl/timeZone --
  // an embedded Chromium build can ship without full ICU timezone data and throw on that).
  // drift/offset are derived from `time` only when it changes; every tick re-adds them to a
  // fresh Date.now() so the clock actually advances (see the comment on driftMsFor/localNow).
  const driftMs = useMemo(() => driftMsFor(time), [time]);
  const offsetMin = useMemo(() => offsetMinFor(time), [time]);
  const [now, setNow] = useState(() => localNow(0, offsetMinFor(null)));
  useEffect(() => {
    const id = setInterval(() => setNow(localNow(driftMs, offsetMin)), 1000);
    return () => clearInterval(id);
  }, [driftMs, offsetMin]);

  const hh = now.getUTCHours();
  const minute = now.getUTCMinutes();
  const ap = hh < 12 ? 'AM' : 'PM';
  const displayHour = hh % 12 || 12;
  const mm = String(minute).padStart(2, '0');
  const dateStr = `${FDAY[now.getUTCDay()]}, ${now.getUTCDate()} ${FMON[now.getUTCMonth()]}`;

  const nightAuto = useMemo(() => {
    const rise = hm(weather?.sunrise ?? null);
    const set = hm(weather?.sunset ?? null);
    if (rise == null || set == null) return false;
    const mins = hh * 60 + minute;
    return !(mins >= rise && mins < set);
  }, [weather?.sunrise, weather?.sunset, hh, minute]);

  const theme: 'dark' | 'light' = themeOverride ?? (themeConfig === 'auto' ? (nightAuto ? 'dark' : 'light') : themeConfig);
  useEffect(() => {
    document.body.classList.toggle('light', theme === 'light');
  }, [theme]);

  // physical buttons: 1 toggles dark/light, 2 toggles C/F, 3 opens the 7-day forecast, 4 enters
  // standby (dim, clock + temperature only), mode opens settings. any key wakes standby first
  // instead of also performing its normal action, matching how a dimmed screen usually behaves.
  // escape backs out of whatever's open; from home it clears the theme override back to auto.
  // the wheel cycles the on-device location preset while settings is open.
  // a brief "pressed" pulse on the physical preset/mode buttons, like a volume HUD acknowledging
  // the press -- purely cosmetic, applied as a transform in the JSX below.
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flashPress = () => {
    setPressed(true);
    if (pressTimer.current) clearTimeout(pressTimer.current);
    pressTimer.current = setTimeout(() => setPressed(false), 130);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (['1', '2', '3', '4', 'm'].includes(e.key)) flashPress();
      if (mode === 'standby') {
        setMode('home');
        return;
      }
      if (e.key === '1') setThemeOverride(theme === 'dark' ? 'light' : 'dark');
      if (e.key === '2') setUnitOverride(u => ((u ?? configUnit) === 'C' ? 'F' : 'C'));
      if (e.key === '3') setMode(m => (m === 'forecast' ? 'home' : 'forecast'));
      if (e.key === '4') setMode(m => (m === 'standby' ? 'home' : 'standby'));
      if (e.key === 'm') setMode(m => (m === 'settings' ? 'home' : 'settings'));
      if (e.key === 'Escape') {
        if (mode === 'home') setThemeOverride(null);
        else setMode('home');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [configUnit, mode, theme]);

  const wheelAccum = useRef(0);
  useEffect(() => {
    const onWheel = (e: WheelEvent) => {
      if (mode !== 'settings') return;
      wheelAccum.current += e.deltaX;
      while (Math.abs(wheelAccum.current) >= 40) {
        const dir = wheelAccum.current > 0 ? 1 : -1;
        setPresetIndex(i => {
          const base = i ?? 0;
          return (base + dir + PRESET_PLACES.length) % PRESET_PLACES.length;
        });
        wheelAccum.current -= dir * 40;
      }
    };
    window.addEventListener('wheel', onWheel);
    return () => window.removeEventListener('wheel', onWheel);
  }, [mode]);

  // swipe down from the top edge: left half refreshes weather, right half opens the phone
  // notification center. gated to starts near the top edge (not any downward drag anywhere) so
  // it reads as a deliberate pull, the same gesture shape as a phone's control/notification center.
  useEffect(() => {
    let start: { x: number; y: number } | null = null;
    const TOP_BAND = 70;
    const THRESHOLD = 50;
    const onDown = (e: PointerEvent) => {
      start = e.clientY <= TOP_BAND ? { x: e.clientX, y: e.clientY } : null;
    };
    const onUp = (e: PointerEvent) => {
      if (!start) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      start = null;
      if (dy < THRESHOLD || Math.abs(dx) > Math.abs(dy)) return;
      if (e.clientX < 400) {
        setRefreshFlash(true);
        refresh().finally(() => setTimeout(() => setRefreshFlash(false), 600));
      } else {
        setMode('notifications');
      }
    };
    window.addEventListener('pointerdown', onDown);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointerup', onUp);
    };
  }, [refresh]);

  // standby dims the physical backlight, remembering whatever it was so leaving standby restores
  // it exactly (auto mode, or a manual level) rather than assuming a specific default.
  const prevBrightnessRef = useRef<{ mode: 'auto' | 'manual'; level: number } | null>(null);
  useEffect(() => {
    if (mode === 'standby') {
      client.hardware
        .stateGet()
        .then(r => {
          if (r.ok) prevBrightnessRef.current = r.response.state.brightness;
        })
        .catch(() => {});
      // setLevel alone does nothing visible while the backlight is in auto mode -- effectiveLevel
      // keeps following the ambient sensor. Standby needs manual mode explicitly.
      client.hardware
        .displaySetMode({ mode: 'manual' })
        .then(() => client.hardware.displaySetLevel({ level: 0.08 }))
        .catch(() => {});
    } else if (prevBrightnessRef.current) {
      const prev = prevBrightnessRef.current;
      prevBrightnessRef.current = null;
      if (prev.mode === 'auto') client.hardware.displaySetMode({ mode: 'auto' }).catch(() => {});
      else client.hardware.displaySetLevel({ level: prev.level }).catch(() => {});
    }
  }, [client, mode]);

  // hands are set imperatively so the 200ms sweep doesn't re-render the whole tree.
  const hourRef = useRef<SVGLineElement>(null);
  const minRef = useRef<SVGLineElement>(null);
  const secRef = useRef<SVGLineElement>(null);
  useEffect(() => {
    const id = setInterval(() => {
      const d = localNow(driftMs, offsetMin);
      const s = d.getUTCSeconds() + d.getUTCMilliseconds() / 1000;
      const m = d.getUTCMinutes() + s / 60;
      const h = (d.getUTCHours() % 12) + m / 60;
      hourRef.current?.setAttribute('transform', `rotate(${(h * 30).toFixed(2)} 100 100)`);
      minRef.current?.setAttribute('transform', `rotate(${(m * 6).toFixed(2)} 100 100)`);
      secRef.current?.setAttribute('transform', `rotate(${(s * 6).toFixed(2)} 100 100)`);
    }, 200);
    return () => clearInterval(id);
  }, [driftMs, offsetMin]);

  if (mode === 'standby') {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 bg-bg" onClick={() => setMode('home')}>
        <div className="text-[96px] font-semibold leading-none tracking-[-4px] text-dim">
          {displayHour}:{mm}
          <span className="ml-2 text-[32px] font-medium text-dim">{ap}</span>
        </div>
        <div className="text-[42px] font-medium text-dim">{weather ? `${weather.temp}°${unit}` : `--°${unit}`}</div>
        <div className="mt-6 text-[12px] font-semibold uppercase tracking-[0.1em] text-dim opacity-60">
          press any button to wake
        </div>
      </div>
    );
  }

  return (
    <div
      className="relative flex h-full w-full flex-col bg-bg text-fg transition-transform duration-100 ease-out"
      style={pressed ? { transform: 'scale(0.985)', boxShadow: 'inset 0 0 40px rgba(0,0,0,0.5)' } : undefined}>
      <div className="absolute right-6 top-3 z-10 flex items-center gap-2">
        <BluetoothGlyph status={phoneStatus} />
        <span className={'text-[13px] font-semibold ' + (error ? 'text-[#ff453a]' : 'text-sec')}>
          {error ? `weather unreachable: ${error}` : conn !== 'open' ? conn : placeLabel}
        </span>
      </div>

      {refreshFlash && (
        <div className="absolute left-1/2 top-3 z-30 -translate-x-1/2 text-[13px] font-semibold uppercase tracking-[0.08em] text-accent">
          refreshing...
        </div>
      )}

      {mode === 'settings' && (
        <div className="absolute inset-0 z-20 flex flex-col gap-5 bg-bg p-10">
          <div className="text-[27px] font-semibold">Settings</div>

          <div>
            <div className="text-[13px] font-semibold uppercase tracking-[0.1em] text-sec">Location -- scroll the knob</div>
            <div className="mt-2 text-[24px] font-semibold">{placeLabel}</div>
            <div className="mt-1 text-[14px] text-sec">
              or type a location in the companion app's settings for this app, which geocodes automatically
            </div>
            {geoError && !preset && <div className="mt-1 text-[14px] text-[#ff453a]">{geoError}</div>}
          </div>

          <div>
            <div className="text-[13px] font-semibold uppercase tracking-[0.1em] text-sec">Temperature unit -- button 2</div>
            <div className="mt-2 text-[24px] font-semibold">{unit === 'F' ? 'Fahrenheit' : 'Celsius'}</div>
          </div>

          <div>
            <div className="text-[13px] font-semibold uppercase tracking-[0.1em] text-sec">Theme -- button 1 toggles, escape for auto</div>
            <div className="mt-2 text-[24px] font-semibold capitalize">
              {theme}
              {themeOverride == null && ' (auto)'}
            </div>
          </div>

          <div>
            <div className="text-[13px] font-semibold uppercase tracking-[0.1em] text-sec">Phone</div>
            <div className="mt-2 flex items-center gap-2 text-[24px] font-semibold">
              <BluetoothGlyph status={phoneStatus} />
              {phoneStatus === 'connected' && (phonePeer?.displayName ?? phonePeer?.device.name ?? 'Connected')}
              {phoneStatus === 'paired' && `${phonePeer?.displayName ?? phonePeer?.device.name ?? 'Phone'} nearby, app not open`}
              {phoneStatus === 'none' && 'Not paired'}
            </div>
            {phoneStatus === 'paired' && (
              <div className="mt-1 text-[14px] text-sec">
                bluetooth sees this phone, but the bridgething companion app isn't running on it right now -- open the
                app on your phone for weather and notifications to work
              </div>
            )}
          </div>

          <div className="mt-auto text-[14px] text-sec">press mode or escape to close</div>
        </div>
      )}

      {mode === 'notifications' && (
        <div className="absolute inset-0 z-20 flex flex-col gap-3 bg-bg p-10">
          <div className="text-[27px] font-semibold">Notifications</div>
          <div className="flex-1 overflow-hidden">
            {notifications.length === 0 ? (
              <div className="text-[16px] text-sec">nothing since this app started</div>
            ) : (
              <div className="flex h-full flex-col gap-3">
                {notifications.slice(0, 6).map(n => (
                  <div key={n.id} className="rounded-2xl bg-card px-4 py-3">
                    <div className="text-[13px] font-semibold uppercase tracking-[0.05em] text-sec">
                      {n.app.displayName ?? n.app.bundleId}
                    </div>
                    <div className="mt-1 text-[18px] font-semibold">{n.title ?? '(no title)'}</div>
                    {n.message && <div className="mt-0.5 truncate text-[15px] text-sec">{n.message}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="text-[14px] text-sec">press escape to close</div>
        </div>
      )}

      {mode === 'forecast' && (
        <div className="absolute inset-0 z-20 flex flex-col gap-4 bg-bg p-10">
          <div className="text-[27px] font-semibold">7-Day Forecast</div>
          <div className="flex flex-1 items-stretch justify-between gap-2">
            {(weather?.daily ?? []).map(d => (
              <div key={d.date} className="flex flex-1 flex-col items-center justify-center gap-2 rounded-2xl bg-card py-4">
                <div className="text-[16px] font-semibold uppercase tracking-[0.05em] text-sec">{d.dow}</div>
                <WeatherIcon icon={d.icon} className="h-10 w-10" />
                <div className="text-[22px] font-semibold">{d.hi}°</div>
                <div className="text-[16px] text-sec">{d.lo}°</div>
              </div>
            ))}
            {!weather && <div className="flex flex-1 items-center justify-center text-sec">loading forecast...</div>}
          </div>
          <div className="text-[14px] text-sec">press button 3 or escape to close</div>
        </div>
      )}

      <div className="flex flex-1 items-center gap-8 px-10 pt-4">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-baseline whitespace-nowrap text-[124px] font-semibold leading-[0.9] tracking-[-5px]">
            {displayHour}:{mm}
            <span className="ml-2.5 text-[42px] font-medium tracking-[-1px] text-sec">{ap}</span>
          </div>
          <div className="mt-2 text-[27px] font-semibold uppercase tracking-[1.5px] text-sec">{dateStr}</div>

          <div className="mt-6 flex flex-col items-start">
            <div className="flex items-center gap-4">
              <WeatherIcon icon={weather?.icon ?? 'cloud'} night={theme === 'dark'} className="h-[66px] w-[66px]" />
              <span className="text-[74px] font-semibold leading-none tracking-[-3px]">
                {weather ? weather.temp : '--'}°{unit}
              </span>
            </div>
            <div className="mt-1 text-[21px] font-medium">{weather ? weather.desc : 'Connecting'}</div>
            {weather && (
              <div className="mt-2 text-[18px] font-semibold tracking-[1px] text-sec">
                H <b className="text-fg">{weather.hi}°</b>&nbsp;&nbsp;&nbsp;L <b className="text-fg">{weather.lo}°</b>
              </div>
            )}
          </div>
        </div>

        <div className="flex w-[300px] flex-none items-center justify-center">
          <svg viewBox="0 0 200 200" className="h-[292px] w-[292px]">
            <circle cx="100" cy="100" r="97" fill="none" stroke="var(--color-hair)" strokeWidth="1.5" />
            <g>
              {TICKS.map((t, i) => (
                <line
                  key={i}
                  x1={t.x1}
                  y1={t.y1}
                  x2={t.x2}
                  y2={t.y2}
                  stroke={t.big ? 'var(--color-fg)' : 'var(--color-sec)'}
                  strokeWidth={t.big ? 2.4 : 1}
                />
              ))}
            </g>
            <line ref={hourRef} x1="100" y1="100" x2="100" y2="54" stroke="var(--color-fg)" strokeWidth="6" strokeLinecap="round" />
            <line ref={minRef} x1="100" y1="100" x2="100" y2="34" stroke="var(--color-fg)" strokeWidth="4" strokeLinecap="round" />
            <line ref={secRef} x1="100" y1="113" x2="100" y2="28" stroke="#ff453a" strokeWidth="2" strokeLinecap="round" />
            <circle cx="100" cy="100" r="5.5" fill="var(--color-fg)" />
            <circle cx="100" cy="100" r="2.6" fill="#ff453a" />
          </svg>
        </div>
      </div>

      {weather && (
        <div className="flex flex-none gap-[1px] px-7 pb-4">
          {weather.hourly.map(h => (
            <div key={h.t} className="flex flex-1 flex-col items-center justify-center gap-[5px] py-1.5">
              <div className="text-[15px] font-semibold tracking-[0.5px] text-sec">{hr12(h.t)}</div>
              <WeatherIcon icon={h.icon} className="h-8 w-8" />
              <div className="text-[24px] font-semibold tabular-nums">{h.temp}°</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
