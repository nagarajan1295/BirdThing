import { BridgethingClient, type ConnectionState, type TimeInfo } from '@bridgething/client';
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
type Weather = {
  temp: number;
  desc: string;
  icon: string;
  hi: number;
  lo: number;
  hourly: Hour[];
  sunrise: string | null;
  sunset: string | null;
};

async function fetchWeather(client: BridgethingClient, lat: number, lon: number, unit: Unit): Promise<Weather> {
  const imperial = unit === 'F';
  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
    `&current=temperature_2m,weather_code` +
    `&hourly=temperature_2m,weather_code` +
    `&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset` +
    `&forecast_days=2&timezone=auto` +
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

  return {
    temp: Math.round(cur.temperature_2m),
    desc,
    icon,
    hi: Math.round(DD.temperature_2m_max[0]),
    lo: Math.round(DD.temperature_2m_min[0]),
    hourly,
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

export default function App() {
  const client = useMemo(() => new BridgethingClient({ url: daemonUrl() }), []);
  const [conn, setConn] = useState<ConnectionState>(client.connectionState);
  const [time, setTime] = useState<TimeInfo | null>(null);
  const [place, setPlace] = useState('New York, NY');
  const [lat, setLat] = useState(40.7128);
  const [lon, setLon] = useState(-74.006);
  const [unit, setUnit] = useState<Unit>('C');
  const [weather, setWeather] = useState<Weather | null>(null);
  const [error, setError] = useState<string | null>(null);

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

    return () => {
      off();
      offTime();
      offConfig();
    };
  }, [client]);

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
    const id = setInterval(refresh, 3 * 60 * 1000);
    return () => clearInterval(id);
  }, [refresh]);

  // wall-clock: apply the daemon's drift + the configured location's IANA zone, since the Car
  // Thing has no RTC and the browser's own zone is not the weather location's zone.
  const tz = time?.tzIana ?? undefined;
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => {
      const drift = time?.wallClockUnixS ? time.wallClockUnixS * 1000 - Date.now() : 0;
      setNow(new Date(Date.now() + drift));
    }, 1000);
    return () => clearInterval(id);
  }, [time?.wallClockUnixS]);

  const zoned = tz ? new Date(now.toLocaleString('en-US', { timeZone: tz })) : now;
  const hh = zoned.getHours();
  const ap = hh < 12 ? 'AM' : 'PM';
  const displayHour = hh % 12 || 12;
  const mm = String(zoned.getMinutes()).padStart(2, '0');
  const dateStr = `${FDAY[zoned.getDay()]}, ${zoned.getDate()} ${FMON[zoned.getMonth()]}`;

  const nightNow = useMemo(() => {
    const rise = hm(weather?.sunrise ?? null);
    const set = hm(weather?.sunset ?? null);
    if (rise == null || set == null) return false;
    const mins = zoned.getHours() * 60 + zoned.getMinutes();
    return !(mins >= rise && mins < set);
  }, [weather?.sunrise, weather?.sunset, zoned]);

  useEffect(() => {
    document.body.classList.toggle('light', !!weather && !nightNow);
  }, [weather, nightNow]);

  // hands are set imperatively so the 200ms sweep doesn't re-render the whole tree.
  const hourRef = useRef<SVGLineElement>(null);
  const minRef = useRef<SVGLineElement>(null);
  const secRef = useRef<SVGLineElement>(null);
  useEffect(() => {
    const id = setInterval(() => {
      const drift = time?.wallClockUnixS ? time.wallClockUnixS * 1000 - Date.now() : 0;
      const d = tz ? new Date(new Date(Date.now() + drift).toLocaleString('en-US', { timeZone: tz })) : new Date(Date.now() + drift);
      const s = d.getSeconds() + d.getMilliseconds() / 1000;
      const m = d.getMinutes() + s / 60;
      const h = (d.getHours() % 12) + m / 60;
      hourRef.current?.setAttribute('transform', `rotate(${(h * 30).toFixed(2)} 100 100)`);
      minRef.current?.setAttribute('transform', `rotate(${(m * 6).toFixed(2)} 100 100)`);
      secRef.current?.setAttribute('transform', `rotate(${(s * 6).toFixed(2)} 100 100)`);
    }, 200);
    return () => clearInterval(id);
  }, [time?.wallClockUnixS, tz]);

  return (
    <div className="relative flex h-full w-full flex-col bg-bg text-fg">
      <div className="absolute right-6 top-3 z-10 text-[13px] font-semibold text-sec">
        {error ? `weather: ${error}` : conn !== 'open' ? conn : place}
      </div>

      <div className="flex flex-1 items-center gap-8 px-10 pt-4">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-baseline whitespace-nowrap text-[124px] font-semibold leading-[0.9] tracking-[-5px]">
            {displayHour}:{mm}
            <span className="ml-2.5 text-[42px] font-medium tracking-[-1px] text-sec">{ap}</span>
          </div>
          <div className="mt-2 text-[27px] font-semibold uppercase tracking-[1.5px] text-sec">{dateStr}</div>

          <div className="mt-6 flex flex-col items-start">
            <div className="flex items-center gap-4">
              <WeatherIcon icon={weather?.icon ?? 'cloud'} night={nightNow} className="h-[66px] w-[66px]" />
              <span className="text-[74px] font-semibold leading-none tracking-[-3px]">
                {weather ? weather.temp : '--'}°
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
