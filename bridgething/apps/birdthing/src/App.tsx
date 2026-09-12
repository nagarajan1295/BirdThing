import { BridgethingClient, type Capabilities, type ConnectionState } from '@bridgething/client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { daemonUrl } from './daemon';

type Detection = { date: string; time: string; com: string; sci: string; conf: number };
type DetectionsResponse = {
  rows: Detection[];
  today_count: number;
  today_species: number;
  err?: string;
};
type StatsResponse = {
  hourly: number[];
  total: number;
  species: number;
  alltime: number;
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
  const iso = `${date}T${time}`;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

export default function App() {
  const client = useMemo(() => new BridgethingClient({ url: daemonUrl() }), []);
  const [conn, setConn] = useState<ConnectionState>(client.connectionState);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [host, setHost] = useState<string | null>(null);
  const [refreshSec, setRefreshSec] = useState(5);
  const [data, setData] = useState<DetectionsResponse | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState(0);
  const [artUrl, setArtUrl] = useState<string | null>(null);

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
      offConfig();
    };
  }, [client]);

  const netAvailable = caps?.available.netFetch ?? true;

  const refresh = useMemo(
    () => async () => {
      if (!host) return;
      try {
        const [d, s] = await Promise.all([
          netGetJson<DetectionsResponse>(client, host, '/api/detections'),
          netGetJson<StatsResponse>(client, host, '/api/stats'),
        ]);
        setData(d);
        setStats(s);
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

  const maxHour = Math.max(1, ...(stats?.hourly ?? [1]));

  return (
    <div className="flex h-full w-full flex-col gap-3 bg-bg p-5 text-off-white">
      <header className="flex items-center justify-between border-b border-rule pb-3">
        <div className="flex items-center gap-3">
          <span className="text-xl">🐦</span>
          <span className="font-display text-title font-medium tracking-display">BirdThing</span>
        </div>
        <div className="flex items-center gap-3 font-mono text-eyebrow uppercase tracking-[0.2em] text-dim">
          {!host && <span className="text-warn">set BirdNET-Pi address in settings</span>}
          {host && !netAvailable && <span className="text-warn">connect a phone for network access</span>}
          {host && netAvailable && error && <span className="text-err">{error}</span>}
          <span>{conn}</span>
        </div>
      </header>

      {!host ? (
        <div className="grid flex-1 place-items-center text-center text-soft">
          <div>
            <div className="text-title">no BirdNET-Pi configured</div>
            <div className="mt-2 font-mono text-body text-dim">
              open this app's settings in the companion app and enter its address
            </div>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 gap-5 overflow-hidden">
          <div className="flex w-[300px] flex-none flex-col gap-3">
            <div className="flex h-40 w-40 items-center justify-center self-center overflow-hidden border border-rule bg-screen">
              {artUrl ? (
                <img src={artUrl} alt="" className="h-full w-full object-cover" />
              ) : (
                <span className="text-4xl opacity-40">🐦</span>
              )}
            </div>
            {current ? (
              <div className="text-center">
                <div className="font-display text-hero font-medium leading-tight tracking-display">
                  {current.com}
                </div>
                <div className="text-body italic text-soft">{current.sci}</div>
                <div className="mt-1 font-mono text-hint text-dim">
                  {Math.round(current.conf * 100)}% confidence · {timeAgo(current.date, current.time)}
                </div>
              </div>
            ) : (
              <div className="text-center font-mono text-body text-dim">listening for birds...</div>
            )}
          </div>

          <div className="flex flex-1 flex-col gap-3 overflow-hidden">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="today" value={data?.today_count ?? 0} />
              <Stat label="species today" value={data?.today_species ?? 0} />
              <Stat label="all time" value={stats?.alltime ?? 0} />
            </div>

            <div className="flex h-10 items-end gap-[2px] border-b border-rule pb-1">
              {(stats?.hourly ?? Array(24).fill(0)).map((c, h) => (
                <div
                  key={h}
                  className="flex-1 bg-accent-soft"
                  style={{ height: `${Math.max(4, (c / maxHour) * 100)}%` }}
                  title={`${h}:00 — ${c}`}
                />
              ))}
            </div>

            <div className="flex-1 overflow-hidden">
              {visible.length === 0 ? (
                <div className="font-mono text-body text-dim">no detections yet</div>
              ) : (
                <ul className="flex h-full flex-col gap-[2px]">
                  {visible.map((r, i) => (
                    <li
                      key={`${r.date}-${r.time}-${r.com}`}
                      className={
                        'flex items-center justify-between border-l-2 px-2 py-1 font-mono text-row ' +
                        (i === selected ? 'border-accent bg-neutral-soft text-off-white' : 'border-transparent text-soft')
                      }>
                      <span className="truncate">{r.com}</span>
                      <span className="ml-3 flex-none text-hint text-dim">
                        {r.time.slice(0, 5)} · {Math.round(r.conf * 100)}%
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-rule px-3 py-2">
      <div className="font-mono text-eyebrow uppercase tracking-[0.2em] text-dim">{label}</div>
      <div className="font-display text-title font-medium">{value}</div>
    </div>
  );
}
