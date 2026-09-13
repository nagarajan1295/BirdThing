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

const VISIBLE_ROWS = 8;
const WHEEL_STEP = 40;

async function netGet(client: BridgethingClient, host: string, path: string) {
  const res = await client.net.fetch({
    request: {
      url: `http://${host}${path}`,
      method: 'GET',
      headers: [],
      body: null,
      timeoutMs: 8000,
      redirect: 'follow',
    },
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

async function netGetJson<T>(client: BridgethingClient, host: string, path: string): Promise<T> {
  const { bytes } = await netGet(client, host, path);
  return JSON.parse(new TextDecoder().decode(bytes)) as T;
}

function timeAgo(date: string, time: string): string {
  const then = new Date(`${date}T${time}`).getTime();
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

function hr12(date: string, time: string, tz?: string): string {
  const d = new Date(`${date}T${time}`);
  if (Number.isNaN(d.getTime())) return time.slice(0, 5);
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: tz });
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
    if (!host || !current) return;
    (async () => {
      try {
        const { bytes, mime } = await netGet(client, host, `/api/image?name=${encodeURIComponent(current.com)}`);
        if (revoked) return;
        blobUrl = URL.createObjectURL(new Blob([bytes], { type: mime || 'image/jpeg' }));
        setArtUrl(blobUrl);
      } catch {
        // no photo available for this species right now
      }
    })();
    return () => {
      revoked = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [client, host, current?.com]);

  // small list thumbnails, fetched once per species and cached for the session
  const fetchedThumbs = useRef(new Set<string>());
  useEffect(() => {
    if (!host) return;
    for (const row of visible) {
      if (fetchedThumbs.current.has(row.com)) continue;
      fetchedThumbs.current.add(row.com);
      netGet(client, host, `/api/image?name=${encodeURIComponent(row.com)}`)
        .then(({ bytes, mime }) => {
          const url = URL.createObjectURL(new Blob([bytes], { type: mime || 'image/jpeg' }));
          setThumbs(prev => ({ ...prev, [row.com]: url }));
        })
        .catch(() => {});
    }
  }, [client, host, visible]);

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

  const tz = time?.tzIana ?? undefined;
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => {
      const drift = time?.wallClockUnixS ? time.wallClockUnixS * 1000 - Date.now() : 0;
      setNow(new Date(Date.now() + drift));
    }, 1000);
    return () => clearInterval(id);
  }, [time?.wallClockUnixS]);
  const clockStr = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: tz });
  const dateStr = now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', timeZone: tz });

  return (
    <div className="relative h-full w-full bg-bg text-fg">
      <div className="fixed left-0 top-0 z-40 flex h-[42px] w-full items-center justify-between bg-bg px-4">
        {player?.track ? (
          <div className="flex max-w-[430px] items-center gap-2 overflow-hidden text-[17px] font-medium">
            <span className="text-green">♫</span>
            <span className="truncate whitespace-nowrap">
              {player.track.title} — {player.track.artist}
            </span>
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

      {!host ? (
        <div className="grid h-full place-items-center text-center text-sec">
          <div>
            <div className="text-[22px] font-semibold text-fg">no BirdNET-Pi configured</div>
            <div className="mt-2 text-[15px]">open this app's settings in the companion app and enter its address</div>
          </div>
        </div>
      ) : (
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
                <div>{host && !netAvailable ? 'connect a phone for network access' : error ? error : 'Listening…'}</div>
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
                        <div className="mt-0.5 text-[14px] text-sec">{hr12(r.date, r.time, tz)}</div>
                      </div>
                      <div className="flex-none text-[17px] font-semibold text-sec">{Math.round(r.conf * 100)}%</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
