import { BridgethingClient, type ConnectionState, type PlayerState, type TimeInfo } from '@bridgething/client';
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
const ICON_EMOJI: Record<string, string> = {
  clear: '☀️',
  mclear: '🌤️',
  partly: '⛅',
  cloud: '☁️',
  fog: '🌫️',
  drizzle: '🌦️',
  rain: '🌧️',
  snow: '❄️',
  storm: '⛈️',
};
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const wmo = (code: number): [string, string] => WMO[code] ?? ['cloud', '—'];

type Hour = { t: string; temp: number; icon: string };
type Day = { date: string; dow: string; icon: string; hi: number; lo: number };
type Weather = {
  temp: number;
  feels: number;
  humidity: number;
  wind: number;
  windUnit: string;
  icon: string;
  desc: string;
  hourly: Hour[];
  daily: Day[];
};

async function fetchWeather(client: BridgethingClient, lat: number, lon: number, unit: Unit): Promise<Weather> {
  const imperial = unit === 'F';
  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
    `&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m` +
    `&hourly=temperature_2m,weather_code` +
    `&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset` +
    `&forecast_days=7&timezone=auto` +
    `&temperature_unit=${imperial ? 'fahrenheit' : 'celsius'}&wind_speed_unit=${imperial ? 'mph' : 'kmh'}`;
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
  for (let i = start; i < Math.min(start + 8, H.time.length); i++) {
    hourly.push({ t: H.time[i].slice(11, 16), temp: Math.round(H.temperature_2m[i]), icon: wmo(H.weather_code[i])[0] });
  }
  const DD = d.daily;
  const daily: Day[] = DD.time.map((date: string, i: number) => ({
    date,
    dow: DOW[new Date(`${date}T12:00:00`).getDay()],
    icon: wmo(DD.weather_code[i])[0],
    hi: Math.round(DD.temperature_2m_max[i]),
    lo: Math.round(DD.temperature_2m_min[i]),
  }));

  return {
    temp: Math.round(cur.temperature_2m),
    feels: Math.round(cur.apparent_temperature),
    humidity: Math.round(cur.relative_humidity_2m),
    wind: Math.round(cur.wind_speed_10m),
    windUnit: imperial ? 'mph' : 'km/h',
    icon,
    desc,
    hourly,
    daily,
  };
}

function useClock(time: TimeInfo | null) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => {
      if (time?.wallClockUnixS) {
        const drift = time.wallClockUnixS * 1000 - Date.now();
        setNow(new Date(Date.now() + drift));
      } else {
        setNow(new Date());
      }
    }, 1000);
    return () => clearInterval(id);
  }, [time?.wallClockUnixS]);
  return now;
}

export default function App() {
  const client = useMemo(() => new BridgethingClient({ url: daemonUrl() }), []);
  const [conn, setConn] = useState<ConnectionState>(client.connectionState);
  const [time, setTime] = useState<TimeInfo | null>(null);
  const [place, setPlace] = useState('Potsdam, NY');
  const [lat, setLat] = useState(44.6701);
  const [lon, setLon] = useState(-74.9774);
  const [unit, setUnit] = useState<Unit>('C');
  const [weather, setWeather] = useState<Weather | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState(0);
  const [player, setPlayer] = useState<PlayerState | null>(null);
  const [artUrl, setArtUrl] = useState<string | null>(null);

  const now = useClock(time);

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
      if (key === 'lat') setLat(Number(value));
      if (key === 'lon') setLon(Number(value));
      if (key === 'unit') setUnit(value === 'F' ? 'F' : 'C');
    };
    Promise.all(
      ['place', 'lat', 'lon', 'unit'].map(key => client.config.get({ key }).then(r => r.ok && applyConfig(key, r.response.value))),
    ).catch(() => {});
    const offConfig = client.config.onChanged(c => applyConfig(c.key, c.value));

    client.player
      .stateGet()
      .then(r => r.ok && setPlayer(r.response.state))
      .catch(() => {});
    const offPlayer = client.player.onSnapshot(r => setPlayer(r.state));

    return () => {
      off();
      offTime();
      offConfig();
      offPlayer();
    };
  }, [client]);

  const refresh = useMemo(
    () => async () => {
      try {
        const w = await fetchWeather(client, lat, lon, unit);
        setWeather(w);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [client, lat, lon, unit],
  );

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10 * 60 * 1000);
    return () => clearInterval(id);
  }, [refresh]);

  const artworkId = player?.track?.artworkId ?? null;
  useEffect(() => {
    let revoked = false;
    let blobUrl: string | null = null;
    setArtUrl(null);
    if (!artworkId) return;
    (async () => {
      const result = await client.asset.get({ id: artworkId, requestId: crypto.randomUUID() });
      if (revoked || !result.ok) return;
      const bytes = new Uint8Array(result.response.bytes as unknown as number[]);
      blobUrl = URL.createObjectURL(new Blob([bytes], { type: result.response.mime ?? 'image/jpeg' }));
      setArtUrl(blobUrl);
    })();
    return () => {
      revoked = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [client, artworkId]);

  const daily = weather?.daily ?? [];
  const wheelAccum = useRef(0);
  useEffect(() => {
    const onWheel = (e: WheelEvent) => {
      wheelAccum.current += e.deltaX;
      while (Math.abs(wheelAccum.current) >= 40) {
        const dir = wheelAccum.current > 0 ? 1 : -1;
        setSelectedDay(s => Math.min(daily.length - 1, Math.max(0, s + dir)));
        wheelAccum.current -= dir * 40;
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedDay(0);
      if (e.key === '1') setUnit(u => (u === 'C' ? 'F' : 'C'));
    };
    window.addEventListener('wheel', onWheel);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKey);
    };
  }, [daily.length]);

  const timeStr = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const dateStr = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
  const playing = player?.playback.state === 'playing';

  return (
    <div className="flex h-full w-full flex-col gap-3 bg-bg p-5 text-off-white">
      <header className="flex items-center justify-between border-b border-rule pb-3">
        <div className="font-mono text-eyebrow uppercase tracking-[0.2em] text-dim">{place}</div>
        <div className="flex items-center gap-3 font-mono text-eyebrow uppercase tracking-[0.2em] text-dim">
          {error && <span className="text-err">{error}</span>}
          <span>{conn}</span>
        </div>
      </header>

      <div className="flex flex-1 items-center gap-8 overflow-hidden">
        <div className="flex flex-none flex-col">
          <div className="font-display text-[4.5rem] font-medium leading-none tracking-display">{timeStr}</div>
          <div className="mt-1 font-mono text-body text-soft">{dateStr}</div>
        </div>

        <div className="h-16 w-px bg-rule" />

        {weather ? (
          <div className="flex flex-1 items-center gap-6">
            <div className="flex items-center gap-3">
              <span className="text-6xl leading-none">{ICON_EMOJI[weather.icon] ?? '☁️'}</span>
              <div>
                <div className="font-display text-hero font-medium">
                  {weather.temp}°{unit}
                </div>
                <div className="font-mono text-hint text-dim">{weather.desc}</div>
              </div>
            </div>
            <div className="font-mono text-hint text-dim">
              feels {weather.feels}° · {weather.humidity}% humidity · wind {weather.wind} {weather.windUnit}
            </div>
          </div>
        ) : (
          <div className="font-mono text-body text-dim">loading weather...</div>
        )}
      </div>

      {weather && (
        <div className="flex justify-between border-t border-rule pt-3">
          {weather.hourly.map(h => (
            <div key={h.t} className="flex flex-col items-center gap-1 font-mono text-hint text-soft">
              <span>{h.t}</span>
              <span className="text-xl leading-none">{ICON_EMOJI[h.icon] ?? '☁️'}</span>
              <span>{h.temp}°</span>
            </div>
          ))}
        </div>
      )}

      {daily.length > 0 && (
        <div className="flex justify-between border-t border-rule pt-3">
          {daily.map((d, i) => (
            <div
              key={d.date}
              className={
                'flex flex-1 flex-col items-center gap-1 border-t-2 pt-2 font-mono text-hint ' +
                (i === selectedDay ? 'border-accent text-off-white' : 'border-transparent text-dim')
              }>
              <span>{d.dow}</span>
              <span className="text-lg leading-none">{ICON_EMOJI[d.icon] ?? '☁️'}</span>
              <span>
                {d.hi}°/{d.lo}°
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 border-t border-rule pt-3">
        {artUrl ? (
          <img src={artUrl} alt="" className="h-10 w-10 flex-none border border-rule object-cover" />
        ) : (
          <div className="h-10 w-10 flex-none border border-rule bg-screen" />
        )}
        {player?.track ? (
          <>
            <div className="min-w-0 flex-1">
              <div className="truncate text-row text-near">{player.track.title ?? 'unknown'}</div>
              <div className="truncate font-mono text-hint text-dim">{player.track.artist ?? ''}</div>
            </div>
            <button
              className="flex-none border border-edge px-4 py-2 font-mono text-row text-near active:bg-neutral-soft"
              onClick={() => (playing ? client.player.pause() : client.player.resume())}>
              {playing ? '❚❚' : '▶'}
            </button>
          </>
        ) : (
          <div className="font-mono text-hint text-dim">nothing playing</div>
        )}
      </div>
    </div>
  );
}
