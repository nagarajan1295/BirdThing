import { BridgethingClient, type Capabilities, type ConnectionState, type PlayerState, type TimeInfo } from '@bridgething/client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { daemonUrl } from './daemon';

type Detection = { date: string; time: string; com: string; sci: string; conf: number };
type DetectionsResponse = {
  rows: Detection[];
  today_count: number;
  today_species: number;
  err?: string;
};
type Photo = { bytes: Uint8Array<ArrayBuffer>; mime: string };

const VISIBLE_ROWS = 8;
const WHEEL_STEP = 40;

async function netGetUrl(client: BridgethingClient, url: string): Promise<Photo> {
  const res = await client.net.fetch({
    request: { url, method: 'GET', headers: [], body: null, timeoutMs: 8000, redirect: 'follow' },
  });
  if (!res.ok) {
    const reason = res.kind === 'domain' ? res.error.error.type : res.error.type;
    throw new Error(reason);
  }
  const { status, body, headers } = res.response.response;
  if (status < 200 || status >= 300) throw new Error(`http ${status}`);
  const bytes = new Uint8Array(body as unknown as number[]);
  const mime = headers.find(h => h.name.toLowerCase() === 'content-type')?.value ?? '';
  return { bytes, mime };
}

function netGet(client: BridgethingClient, host: string, path: string): Promise<Photo> {
  return netGetUrl(client, `http://${host}${path}`);
}

async function netGetJson<T>(client: BridgethingClient, host: string, path: string): Promise<T> {
  const { bytes } = await netGet(client, host, path);
  return JSON.parse(new TextDecoder().decode(bytes)) as T;
}

// no BirdNET-Pi (or any bird-ID backend) required: Wikipedia's free, keyless REST API gives a
// real photo for a species name, tunneled through the phone the same way the Pi's /api/image is.
async function fetchWikiPhoto(client: BridgethingClient, species: string): Promise<Photo | null> {
  try {
    const sum = await netGetUrl(client, `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(species)}`);
    const json = JSON.parse(new TextDecoder().decode(sum.bytes));
    const imgUrl: string | undefined = json.thumbnail?.source ?? json.originalimage?.source;
    if (!imgUrl) return null;
    return await netGetUrl(client, imgUrl);
  } catch {
    return null;
  }
}

// a rotating cast of common, easy-to-photograph North American birds for demo mode -- anyone
// installing the app sees a live, working dashboard with zero setup, no Pi required.
const DEMO_BIRDS: [string, string][] = [
  ['Black-capped Chickadee', 'Poecile atricapillus'],
  ['American Robin', 'Turdus migratorius'],
  ['Blue Jay', 'Cyanocitta cristata'],
  ['Northern Cardinal', 'Cardinalis cardinalis'],
  ['Song Sparrow', 'Melospiza melodia'],
  ['American Goldfinch', 'Spinus tristis'],
  ['Mourning Dove', 'Zenaida macroura'],
  ['Red-winged Blackbird', 'Agelaius phoeniceus'],
  ['Downy Woodpecker', 'Dryobates pubescens'],
  ['White-breasted Nuthatch', 'Sitta carolinensis'],
  ['Tufted Titmouse', 'Baeolophus bicolor'],
  ['Carolina Wren', 'Thryothorus ludovicianus'],
];
const DEMO_INTERVAL_MS = 18000;

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}
function fmtDate(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}
function fmtTime(d: Date): string {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}
function demoDetection(): Detection {
  const [com, sci] = DEMO_BIRDS[Math.floor(Math.random() * DEMO_BIRDS.length)];
  const now = new Date();
  return { date: fmtDate(now), time: fmtTime(now), com, sci, conf: 0.7 + Math.random() * 0.27 };
}

function timeAgo(date: string, time: string): string {
  const then = new Date(`${date}T${time}`).getTime();
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

// the detection's date/time strings are already local (the Pi's local time in live mode, the
// device's own local time in demo mode) -- no zone conversion needed, and no Intl/toLocaleTimeString
// either (an embedded Chromium build can ship without full ICU timezone data and throw on a
// `timeZone` option, which would crash the whole render).
function hr12(_date: string, time: string): string {
  const [hStr, mStr] = time.split(':');
  const h = Number(hStr);
  if (Number.isNaN(h)) return time.slice(0, 5);
  const ap = h < 12 ? 'AM' : 'PM';
  return `${h % 12 || 12}:${mStr} ${ap}`;
}

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// see the identical helpers (and the comment on why driftMs must be captured once, not
// recomputed from Date.now() on every tick) in weatherthing's App.tsx
function driftMsFor(time: TimeInfo | null): number {
  return time?.wallClockUnixS ? time.wallClockUnixS * 1000 - Date.now() : 0;
}
function offsetMinFor(time: TimeInfo | null): number {
  return (time?.utcOffsetMinutes ?? -new Date().getTimezoneOffset()) + (time?.dstOffsetMinutes ?? 0);
}
function localNow(driftMs: number, offsetMin: number): Date {
  return new Date(Date.now() + driftMs + offsetMin * 60000);
}

export default function App() {
  const client = useMemo(() => new BridgethingClient({ url: daemonUrl() }), []);
  const [conn, setConn] = useState<ConnectionState>(client.connectionState);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [host, setHost] = useState<string | null>(null);
  const [refreshSec, setRefreshSec] = useState(5);
  const [data, setData] = useState<DetectionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState(0);
  const [artUrl, setArtUrl] = useState<string | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [time, setTime] = useState<TimeInfo | null>(null);
  const [player, setPlayer] = useState<PlayerState | null>(null);

  const demo = !host;

  useEffect(() => {
    const off = client.on(event => {
      if (event.type === 'open' || event.type === 'close' || event.type === 'connecting') {
        setConn(client.connectionState);
      }
    });
    client.capabilities
      .get()
      .then(r => r.ok && setCaps(r.response.capabilities))
      .catch(() => {});
    const offCaps = client.capabilities.onSnapshot(r => setCaps(r.capabilities));

    client.time
      .get()
      .then(r => r.ok && setTime(r.response.time))
      .catch(() => {});
    const offTime = client.time.onChanged(t => setTime(t.time));

    client.player
      .stateGet()
      .then(r => r.ok && setPlayer(r.response.state))
      .catch(() => {});
    const offPlayer = client.player.onSnapshot(r => setPlayer(r.state));

    const applyConfig = (key: string, value: string | null) => {
      if (key === 'host') setHost(value && value.trim() ? value.trim() : null);
      if (key === 'refreshSec') {
        const n = value ? Number(value) : NaN;
        setRefreshSec(Number.isFinite(n) && n >= 2 ? n : 5);
      }
    };
    Promise.all([client.config.get({ key: 'host' }), client.config.get({ key: 'refreshSec' })])
      .then(([h, r]) => {
        if (h.ok) applyConfig('host', h.response.value);
        if (r.ok) applyConfig('refreshSec', r.response.value);
      })
      .catch(() => {});
    const offConfig = client.config.onChanged(c => applyConfig(c.key, c.value));

    return () => {
      off();
      offCaps();
      offTime();
      offPlayer();
      offConfig();
    };
  }, [client]);

  const netAvailable = caps?.available.netFetch ?? true;

  const refresh = useMemo(
    () => async () => {
      if (!host) return;
      try {
        const d = await netGetJson<DetectionsResponse>(client, host, '/api/detections');
        setData(d);
        setError(d.err ?? null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [client, host],
  );

  useEffect(() => {
    if (!host || !netAvailable) return;
    refresh();
    const id = setInterval(refresh, Math.max(2, refreshSec) * 1000);
    return () => clearInterval(id);
  }, [refresh, host, netAvailable, refreshSec]);

  // demo mode: a self-contained rotating feed, no backend of any kind required.
  useEffect(() => {
    if (!demo) return;
    const tick = () => {
      setData(prev => {
        const rows = [demoDetection(), ...(prev?.rows ?? [])].slice(0, 20);
        return { rows, today_count: (prev?.today_count ?? 0) + 1, today_species: new Set(rows.map(r => r.com)).size };
      });
    };
    tick();
    const id = setInterval(tick, DEMO_INTERVAL_MS);
    return () => clearInterval(id);
  }, [demo]);

  useEffect(() => {
    if (!demo) setData(null);
  }, [demo]);

  const rows = data?.rows ?? [];
  const visible = rows.slice(0, VISIBLE_ROWS);
  const current = visible[selected] ?? visible[0] ?? null;

  useEffect(() => {
    if (selected > visible.length - 1) setSelected(Math.max(0, visible.length - 1));
  }, [visible.length, selected]);

  // the big hero photo, for whichever row is selected
  useEffect(() => {
    let revoked = false;
    let blobUrl: string | null = null;
    setArtUrl(null);
    if (!current) return;
    (async () => {
      const photo = demo ? await fetchWikiPhoto(client, current.com) : await netGet(client, host!, `/api/image?name=${encodeURIComponent(current.com)}`).catch(() => null);
      if (revoked || !photo) return;
      blobUrl = URL.createObjectURL(new Blob([photo.bytes], { type: photo.mime || 'image/jpeg' }));
      setArtUrl(blobUrl);
    })();
    return () => {
      revoked = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [client, host, demo, current?.com]);

  // small list thumbnails, fetched once per species and cached for the session
  const fetchedThumbs = useRef(new Set<string>());
  useEffect(() => {
    for (const row of visible) {
      if (fetchedThumbs.current.has(row.com)) continue;
      fetchedThumbs.current.add(row.com);
      (demo ? fetchWikiPhoto(client, row.com) : netGet(client, host!, `/api/image?name=${encodeURIComponent(row.com)}`).catch(() => null)).then(photo => {
        if (!photo) return;
        const url = URL.createObjectURL(new Blob([photo.bytes], { type: photo.mime || 'image/jpeg' }));
        setThumbs(prev => ({ ...prev, [row.com]: url }));
      });
    }
  }, [client, host, demo, visible]);

  const wheelAccum = useRef(0);
  useEffect(() => {
    const onWheel = (e: WheelEvent) => {
      wheelAccum.current += e.deltaX;
      while (Math.abs(wheelAccum.current) >= WHEEL_STEP) {
        const dir = wheelAccum.current > 0 ? 1 : -1;
        setSelected(s => Math.min(visible.length - 1, Math.max(0, s + dir)));
        wheelAccum.current -= dir * WHEEL_STEP;
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(0);
      if (e.key === '1') refresh();
    };
    window.addEventListener('wheel', onWheel);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKey);
    };
  }, [visible.length, refresh]);

  const driftMs = useMemo(() => driftMsFor(time), [time]);
  const offsetMin = useMemo(() => offsetMinFor(time), [time]);
  const [now, setNow] = useState(() => localNow(0, offsetMinFor(null)));
  useEffect(() => {
    const id = setInterval(() => setNow(localNow(driftMs, offsetMin)), 1000);
    return () => clearInterval(id);
  }, [driftMs, offsetMin]);
  const clockHour = now.getUTCHours();
  const clockStr = `${clockHour % 12 || 12}:${String(now.getUTCMinutes()).padStart(2, '0')} ${clockHour < 12 ? 'AM' : 'PM'}`;
  const dateStr = `${DOW[now.getUTCDay()]}, ${MON[now.getUTCMonth()]} ${now.getUTCDate()}`;

  return (
    <div className="relative h-full w-full bg-bg text-fg">
      <div className="fixed left-0 top-0 z-40 flex h-[42px] w-full items-center justify-between bg-bg px-4">
        {player?.track ? (
          <div className="flex max-w-[380px] items-center gap-2 overflow-hidden text-[17px] font-medium">
            <span className="text-green">♫</span>
            <span className="truncate whitespace-nowrap">
              {player.track.title} — {player.track.artist}
            </span>
          </div>
        ) : demo ? (
          <div className="flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.1em] text-sec">
            <span className="rounded-full bg-white/10 px-2.5 py-1">Demo</span>
            <span>no BirdNET-Pi configured -- open settings to connect your own</span>
          </div>
        ) : (
          <div />
        )}
        <div className="flex items-center gap-3.5 whitespace-nowrap text-[16px] font-medium text-sec">
          <span>{dateStr}</span>
          <span className={'flex items-center gap-1.5 ' + (conn === 'open' ? 'text-green' : 'text-sec')}>
            <span className={'h-[9px] w-[9px] rounded-full ' + (conn === 'open' ? 'bg-green' : 'bg-sec')} />
            {conn === 'open' ? 'Live' : conn}
          </span>
          <span className="tabular-nums text-fg">{clockStr}</span>
        </div>
      </div>

      <div className="grid h-full grid-cols-[472px_328px] grid-rows-[42px_438px]">
        <div className="relative col-start-1 row-start-2 mb-3.5 ml-4 mr-2.5 mt-1.5 flex flex-col overflow-hidden rounded-3xl bg-[#0c0c0e]">
          {current && artUrl && (
            <div
              className="absolute inset-0 scale-125"
              style={{ backgroundImage: `url(${artUrl})`, backgroundSize: 'cover', backgroundPosition: 'center', filter: 'blur(34px) brightness(.4)' }}
            />
          )}
          {current ? (
            <>
              <div
                className="relative h-[56%] flex-none bg-contain bg-center bg-no-repeat transition-opacity duration-500"
                style={artUrl ? { backgroundImage: `url(${artUrl})` } : undefined}
              />
              <div
                className="relative min-h-0 flex-1 overflow-hidden px-6 pb-5 pt-4.5"
                style={{ background: 'linear-gradient(0deg, rgba(0,0,0,.92), rgba(0,0,0,.55) 55%, transparent)' }}>
                <div className="text-[42px] font-bold leading-[1.04] tracking-tight">{current.com}</div>
                <div className="mt-1 text-[19px] italic text-[#c7c7cc]">{current.sci}</div>
                <div className="mt-4 flex items-center gap-3">
                  <span className="rounded-full bg-white/16 px-3.5 py-1.5 text-[16px] font-semibold backdrop-blur">
                    {Math.round(current.conf * 100)}%
                  </span>
                  <span className="text-[16px] font-medium text-[#c7c7cc]">{timeAgo(current.date, current.time)}</span>
                </div>
              </div>
            </>
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3.5 text-sec">
              <div className="text-[64px]">🐦</div>
              <div>{!demo && !netAvailable ? 'connect a phone for network access' : error ? error : 'Listening…'}</div>
            </div>
          )}
        </div>

        <div className="col-start-2 row-start-2 mb-3.5 ml-1.5 mr-4 mt-1.5 flex min-h-0 flex-col">
          <div className="mb-2.5 flex gap-2">
            <div className="flex-1 rounded-2xl bg-card px-3.5 py-2.5">
              <div className="text-[30px] font-bold leading-none tracking-tight">{data?.today_count ?? 0}</div>
              <div className="mt-1 text-[12px] font-medium text-sec">Today</div>
            </div>
            <div className="flex-1 rounded-2xl bg-card px-3.5 py-2.5">
              <div className="text-[30px] font-bold leading-none tracking-tight">{data?.today_species ?? 0}</div>
              <div className="mt-1 text-[12px] font-medium text-sec">Species</div>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-hidden">
            {visible.length === 0 ? (
              <div className="p-2 text-[15px] text-sec">no detections yet</div>
            ) : (
              <div className="flex h-full flex-col gap-0.5">
                {visible.map((r, i) => (
                  <div
                    key={`${r.date}-${r.time}-${r.com}`}
                    className={'flex items-center gap-3 rounded-2xl p-2.5 ' + (i === selected ? 'bg-card2' : '')}>
                    {thumbs[r.com] ? (
                      <img src={thumbs[r.com]} alt="" className="h-[50px] w-[50px] flex-shrink-0 rounded-[13px] object-cover" />
                    ) : (
                      <div className="h-[50px] w-[50px] flex-shrink-0 rounded-[13px] bg-[#1c1c1e]" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[20px] font-semibold">{r.com}</div>
                      <div className="mt-0.5 text-[14px] text-sec">{hr12(r.date, r.time)}</div>
                    </div>
                    <div className="flex-none text-[17px] font-semibold text-sec">{Math.round(r.conf * 100)}%</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
