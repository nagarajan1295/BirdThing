# WeatherThing

## 0.4.2

remove the button-press screen-pulse animation (felt like a glitch when toggling theme)

## 0.4.1

settings: autocomplete-driven location picker, hide raw lat/lon inputs, single Save button (drop the dead Save-to-device action)

## 0.4.0

remove the on-screen button legend, show unit letter even with no weather data, add a real phone/Bluetooth status glyph and settings row (distinguishing Bluetooth-paired-but-app-closed from genuinely connected), a button-press screen animation, and swipe gestures: top-left pulls to refresh, top-right opens a live notification center

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
