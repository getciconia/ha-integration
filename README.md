# Ciconia for Home Assistant

<img src="custom_components/ciconia/brand/logo.png" alt="Ciconia" height="64">

See where your [Ciconia](https://getciconia.com) GPS trackers are, right in
Home Assistant: each tracker becomes a device with a location on the map,
battery, speed, signal and more, ready for zones, automations and
dashboards.

## Use cases

- **Arrive/leave automations**: the tracker entity works with Home
  Assistant zones: open the gate when the car gets home, notify when the
  bike leaves the garage at night.
- **Low battery or silent tracker**: alert when *Battery* drops below 20 %
  or *Stale* turns on (no fresh fix for an hour).
- **Map and history**: put trackers on a map card; the history and logbook
  keep the route.

## Requirements

- Home Assistant **2026.3** or newer.
- A Ciconia account with at least one tracker (trackers added later appear
  on their own).

## Installation

**HACS**: in HACS → ⋮ → *Custom repositories*, add this repository with
category *Integration*, install **Ciconia** and restart Home Assistant.

**Manual**: copy `custom_components/ciconia/` into the `custom_components/`
folder of your Home Assistant configuration and restart.

## Setup

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ciconia)

Settings → Devices & services → **Add integration** → **Ciconia** →
**Submit**. Home Assistant shows a short code and a link: open the link,
sign in to Ciconia, check the code and click **Allow**. Home Assistant
continues on its own and lists your trackers; untick any you don't want.
No ids, passwords or tokens to copy.

### Setup parameters

| Parameter | Where | Description |
| --- | --- | --- |
| Trackers | After approving the code | Which trackers to add. Untick to leave one out. |

The first step also has an *Advanced* section with the server address. It's
for development only; leave it as is.

## Configuration options

Devices & services → Ciconia → **Configure**:

| Option | Default | Description |
| --- | --- | --- |
| Trackers | all | Unticked trackers are removed from Home Assistant; new trackers on the account are added automatically. |
| Polling interval | 5 s (minimum 5) | How often Home Assistant asks Ciconia for fresh positions. |
| Consider stale after | 3600 s (minimum 60) | When the *Stale* sensor turns on. A tracker that sleeps for hours to save battery needs a longer value. |

## Supported devices

Every tracker sold or registered with Ciconia, whatever its model. Which
sensors have values depends on what the tracker reports: a sensor stays
*unknown* when the tracker doesn't report that measurement.

## Entities

Each tracker is one device with:

| Entity | Type | Notes |
| --- | --- | --- |
| *Tracker name* | `device_tracker` | GPS location. The state is the Home Assistant zone it's in, or *Away*. Attributes: latitude, longitude, GPS accuracy (HDOP × 5 m, 0 when unknown), battery level, altitude, speed, fixed time, fix age. |
| Battery | sensor, 0–100 % | Only for trackers that report a percentage. |
| Speed | sensor, km/h, 0 or more | Speed at the last fix. |
| Altitude | sensor, m | Height above sea level, from GPS. Less precise than latitude and longitude. |
| Last fix | sensor, timestamp | When the position was measured, not when Home Assistant polled. |
| Stale | binary sensor (problem) | On when the last fix is older than *Consider stale after* (default 1 hour), or when there's no fix yet. |
| Fix age | diagnostic, s, 0 or more | Seconds since the last fix. |
| GSM signal | diagnostic, 0–5 | Mobile signal bars: 0 none, 5 best. |
| GPS signal | diagnostic, 0–5 | Position quality, from HDOP: 5 ideal (under 1), 4 excellent (1–2), 3 good (2–5), 2 moderate (5–10), 1 fair (10–20), 0 poor (over 20) or no fix. |
| Visible satellites | diagnostic, 0 or more | GPS satellites the tracker can see. It needs at least 4 for a position, and more usually means a more precise one. 0 means no view of the sky, e.g. in a garage. |
| Chip temperature | diagnostic, °C | Internal temperature of the tracker's electronics, not the air around it. Usually warmer than its surroundings. |
| HDOP | diagnostic, 0 or more, disabled by default | Raw horizontal dilution of precision: how well spread the satellites are. Lower is better; under 2 is good. |
| GSM operator code | diagnostic, disabled by default | Mobile network: country code (MCC) followed by operator code (MNC), e.g. `26003` = Orange Poland. |

## How data is updated

Ciconia is a cloud service, so Home Assistant polls it (`cloud_polling`).
Every polling interval it fetches the account's tracker list and then each
tracker's latest position. Ciconia passes each request on live, nothing is
cached in between. A tracker that can't be reached in one round shows as
*unavailable* until the next successful poll; if none can be reached the
integration logs it once and keeps retrying.

Positions are only as fresh as the tracker's own reports: a tracker that
reports every few minutes doesn't move more often in Home Assistant even
with 5 s polling. *Last fix* and *Fix age* tell how old the data is.

## Examples

Notify when the car's battery runs low:

```yaml
automation:
  - alias: Car tracker battery low
    triggers:
      - trigger: numeric_state
        entity_id: sensor.car_battery
        below: 20
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Car tracker battery is at {{ states('sensor.car_battery') }} %"
```

Tell when the car arrives home:

```yaml
automation:
  - alias: Car arrived home
    triggers:
      - trigger: zone
        entity_id: device_tracker.car
        zone: zone.home
        event: enter
    actions:
      - action: notify.mobile_app_phone
        data:
          message: The car is home.
```

## Known limitations

- Needs an internet connection: Ciconia is a cloud service.
- Positions come only as often as the tracker reports; polling faster
  doesn't make a sleeping tracker report.
- Battery shows only for trackers that report a percentage (some report a
  supply voltage, which isn't shown).
- No address, heading or course: latitude, longitude, altitude and speed
  only.

## Troubleshooting

- **"Could not reach the Ciconia server" during setup**: check that Home
  Assistant has internet access.
- **The code expired**: submit again for a new one; codes are valid for
  10 minutes.
- **Home Assistant asks to re-authenticate**: the connection was removed
  on the Ciconia website (Integrations → Disconnect). Re-authenticate and
  approve the new code with the same account.
- **A tracker is missing**: trackers still activating are added once
  they're active; also check it's ticked under **Configure**.
- **Entities are unavailable**: Ciconia couldn't reach the tracker this
  round; it recovers on its own. If it persists, download the diagnostics
  (Devices & services → Ciconia → ⋮ → Download diagnostics; tokens and
  positions are removed) and open an issue.
- Debug logs: Devices & services → Ciconia → ⋮ → *Enable debug logging*.

## Removal

Devices & services → Ciconia → ⋮ → **Delete**. To revoke Home Assistant's
access as well, click **Disconnect** next to it on the Integrations page of
the Ciconia website. Installed through HACS? Remove it there too, then
restart.

## Contributing

Bug reports and pull requests are welcome: see
[CONTRIBUTING.md](CONTRIBUTING.md). Setting up, testing and releasing are
in [DEVELOPMENT.md](DEVELOPMENT.md).
