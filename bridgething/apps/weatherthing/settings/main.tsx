import { settings, type ConfigField, type SettingsContext } from '@bridgething/client/settings';
import { useEffect, useRef, useState, type FormEvent, type InputEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const LOCATION_KEY = 'place';
// lat/lon are a silent fallback the app geocodes into on its own; showing raw numbers
// just confuses people who only want to type a city name.
const HIDDEN_KEYS = new Set(['lat', 'lon']);
const SEARCH_DEBOUNCE_MS = 300;

type GeoSuggestion = { label: string; lat: number; lon: number };

function fieldMeta(field: ConfigField): { key: string; label: string } {
  return { key: field.data.key, label: field.data.label };
}

async function searchPlaces(query: string): Promise<GeoSuggestion[]> {
  if (query.trim().length < 2) return [];
  const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(query)}&count=6&language=en&format=json`;
  // settings.fetch tunnels through the phone's own network, sidestepping the file:// webview's CORS checks.
  const res = await settings.fetch(url);
  if (!res.ok) return [];
  const data = await res.json();
  return (data.results ?? []).map((r: { name: string; admin1?: string; country?: string; latitude: number; longitude: number }) => ({
    label: [r.name, r.admin1, r.country].filter(Boolean).join(', '),
    lat: r.latitude,
    lon: r.longitude,
  }));
}

function Settings() {
  const [ctx, setCtx] = useState<SettingsContext | null>(null);
  const [fields, setFields] = useState<ConfigField[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);
  const [suggestions, setSuggestions] = useState<GeoSuggestion[]>([]);
  const [searching, setSearching] = useState(false);
  const searchToken = useRef(0);

  useEffect(() => {
    (async () => {
      try {
        setCtx(await settings.context());
        const [schema, entries] = await Promise.all([settings.config.fields(), settings.config.list()]);
        setFields(schema);
        setValues(Object.fromEntries(entries.map(e => [e.key, e.value])));
      } catch (err) {
        setStatus(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  function onLocationInput(text: string) {
    setValues(v => ({ ...v, [LOCATION_KEY]: text }));
    const token = ++searchToken.current;
    if (text.trim().length < 2) {
      setSuggestions([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    setTimeout(async () => {
      const results = await searchPlaces(text).catch(() => []);
      if (searchToken.current !== token) return; // input changed again since this search started
      setSuggestions(results);
      setSearching(false);
    }, SEARCH_DEBOUNCE_MS);
  }

  function pickSuggestion(s: GeoSuggestion) {
    searchToken.current++; // drop any search still in flight
    setValues(v => ({ ...v, [LOCATION_KEY]: s.label, lat: String(s.lat), lon: String(s.lon) }));
    setSuggestions([]);
    setSearching(false);
  }

  async function saveConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setStatus('saving...');
    try {
      for (const field of fields) {
        const { key } = fieldMeta(field);
        await settings.config.set(key, values[key] ?? '');
      }
      setStatus('saved');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main>
      <h1>{ctx?.name ?? 'weatherthing'} settings</h1>
      <p className="hint">{ctx ? `${ctx.webappId} on ${ctx.deviceId}` : 'connecting to the companion host...'}</p>

      <form onSubmit={saveConfig}>
        {fields.length === 0 && <p className="hint">this webapp declares no config fields yet.</p>}
        {fields.filter(f => !HIDDEN_KEYS.has(f.data.key)).map(field => {
          const { key, label } = fieldMeta(field);
          const value = values[key] ?? '';

          if (key === LOCATION_KEY) {
            return (
              <div className="field" key={key}>
                <label htmlFor={key}>{label}</label>
                <input
                  id={key}
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="type a city, region or country"
                  value={value}
                  onInput={e => onLocationInput((e.target as HTMLInputElement).value)}
                />
                {searching && <p className="hint">searching...</p>}
                {suggestions.length > 0 && (
                  <ul className="suggestions">
                    {suggestions.map(s => (
                      <li key={`${s.label}|${s.lat}|${s.lon}`}>
                        <button type="button" onClick={() => pickSuggestion(s)}>
                          {s.label}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          }

          const onInput = (e: InputEvent<HTMLInputElement | HTMLSelectElement>) =>
            setValues({ ...values, [key]: (e.target as HTMLInputElement).value });
          return (
            <div className="field" key={key}>
              <label htmlFor={key}>{label}</label>
              {field.type === 'enum' ? (
                <select id={key} value={value} onInput={onInput}>
                  {field.data.choices.map(choice => (
                    <option value={choice} key={choice}>
                      {choice}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id={key}
                  type={field.type === 'number' ? 'number' : field.type === 'secret' ? 'password' : 'text'}
                  value={value}
                  onInput={onInput}
                />
              )}
            </div>
          );
        })}

        <div className="row">
          <button type="submit" disabled={saving}>
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button type="button" className="secondary" onClick={() => settings.done()}>
            Done
          </button>
        </div>
      </form>

      <p className="status">{status}</p>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<Settings />);
