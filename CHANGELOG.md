# Changelog

## 0.2.1

- A tracker that can't be fetched keeps its last values for up to 2 minutes
  instead of going *unavailable* on the first failed poll. Short outages no
  longer make entities flip between unavailable and back every poll. *Fix
  age* keeps counting meanwhile.
- A tracker that stays unreachable is logged once, and once when it's back.

## 0.2.0

First public release.

- Link your Ciconia account with a short code, no tokens to copy.
- One entry per account; trackers added later appear on their own.
- Per tracker: a GPS `device_tracker` plus battery, speed, altitude, last fix,
  fix age, GSM and GPS signal, satellites and chip temperature.
- Options: which trackers and the polling interval.
- Diagnostics with the token and positions removed.
- The tracker's location shows as the device's main entity, not under Diagnostic.
- A tracker renamed in Ciconia is renamed in Home Assistant on the next poll.
