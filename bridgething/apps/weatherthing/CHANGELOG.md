# WeatherThing

## 0.3.0

fix a real location bug (an on-device preset silently locked out the companion app's typed location forever), remap buttons (1 theme, 2 unit, 3 seven-day forecast, 4 standby with real backlight dimming, mode opens settings), and show real geocode errors instead of a misleading message

## 0.2.1

fix the clock/analog hands actually being frozen (a drift-math bug that cancelled Date.now() out entirely); add an on-device settings screen (button 4): location presets via the knob, unit and theme status

## 0.2.0

fix a real-hardware crash in the clock/analog hands, add location search, theme + button controls

## 0.1.1

match the real WeatherThing look: big digital clock, analog clock, colored weather icons

## 0.1.0

First bridgething release: a big clock, current conditions from Open-Meteo, an
hourly forecast strip you scroll with the knob, and a now-playing footer.
