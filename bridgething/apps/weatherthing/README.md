# 🌤️ WeatherThing

A clock and weather station for the [Spotify Car Thing](https://bridgething.com), built for the
[bridgething app jam](https://bridgething.com/appjam/). A big digital clock, a faithful 292px
analog clock with a sweeping second hand, current conditions and an hourly forecast from
Open‑Meteo (no Raspberry Pi needed — just a paired phone or desktop with internet), the original
multi‑tone weather icons, and an on‑device settings screen (physical button 4).

**Install:** paste this catalog URL into the bridgething companion app —
`https://nagarajan1295.github.io/BirdThing/catalog.v1.json`

| Night (auto dark) | Day (auto light) | On‑device settings |
|---|---|---|
| ![WeatherThing at night](screenshots/01.png) | ![WeatherThing by day](screenshots/02.png) | ![WeatherThing settings screen](screenshots/03.png) |

Controls: button **1** toggles dark/light, **2** toggles °C/°F, **3** opens a 7‑day forecast,
**4** enters a dimmed standby (clock + temperature only, real backlight dimming), and **mode**
opens on‑device settings (knob‑scrollable location list). Theme auto‑switches on real
sunrise/sunset when left on auto. A location typed into the companion app's settings always
takes over from an on‑device pick.

## Dev workflow

```bash
cd bridgething
bun install
bun run dev                                  # http://localhost:5173, proxies a connected Car Thing
bun run --cwd apps/weatherthing dev:device   # push + hot-reload onto real hardware
bun run --cwd apps/weatherthing push         # build and install onto the connected device
bun run check                                # typecheck, build, bundle, validate the catalog
```

See [`../../CLAUDE.md`](../../CLAUDE.md) for the full workspace reference.
