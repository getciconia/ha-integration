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
| *Tracker name* | `device_tracker` | GPS location. Accuracy is estimated from HDOP (HDOP × 5 m). Attributes: altitude, speed, fixed time, fix age. |
| Battery | sensor, % | Only when the tracker reports a percentage. |
| Speed | sensor, km/h | |
| Altitude | sensor, m | |
| Last fix | sensor, timestamp | When the position was measured (not when Home Assistant polled). |
| Stale | binary sensor | On when the last fix is older than *Consider stale after*. |
| Fix age | diagnostic, s | Seconds since the last fix. |
| GSM signal | diagnostic, 0–5 | |
| GPS signal | diagnostic, 0–5 | From HDOP: 5 ideal (<1), 4 excellent, 3 good, 2 moderate, 1 fair, 0 poor or no fix. |
| Visible satellites | diagnostic | |
| Chip temperature | diagnostic, °C | |
| HDOP | diagnostic, disabled by default | Raw horizontal dilution of precision. |
| GSM operator code | diagnostic, disabled by default | Mobile network code (MCC+MNC). |

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

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt

ruff check . && ruff format --check .
mypy                      # strict, settings in pyproject.toml
pytest --cov              # coverage must stay >= 95 %
```

Tests run against a real `homeassistant` core install
(`pytest-homeassistant-custom-component`), not mocks of Home Assistant, so
they exercise the actual config flow, coordinator and entity platforms.
`requirements_test.txt` is pinned; bump `homeassistant` and
`pytest-homeassistant-custom-component` together.

### A Home Assistant to try it in (Docker)

`dev/ha/` runs a throwaway Home Assistant with `custom_components/ciconia/`
mounted straight from this repository (read-only): edit the code, then
`restart` to pick it up.

```bash
dev/ha/scripts/ha-dev.sh up       # start, onboard automatically, print the login
dev/ha/scripts/ha-dev.sh restart  # after editing the integration
dev/ha/scripts/ha-dev.sh logs     # follow the logs
dev/ha/scripts/ha-dev.sh down     # stop
dev/ha/scripts/ha-dev.sh reset    # wipe its state and start clean
```

`up` prints the admin login it created (`admin` / `admin` unless you set
`DEV_HA_USERNAME` / `DEV_HA_PASSWORD`). Log in, add the Ciconia integration
and link your own Ciconia account.

### End-to-end test (maintainers)

`dev/ha/scripts/integration_test.py` sets up a separate throwaway Home
Assistant, adds the integration through the real config flow, approves the
link code by signing in to the Ciconia website as a test account, and checks
the resulting entities. It needs a real account with at least one active
tracker:

```bash
CICONIA_EMAIL=you@example.com CICONIA_PASSWORD=... dev/ha/scripts/ha-dev.sh test
```

(or put them in a gitignored `dev/ha/.env`). It signs in the way a browser
does, so it may need updating when the website's pages change. It doesn't run
in CI here.

### Releasing

- CI runs hassfest and the HACS check on every push.
- `custom_components/ciconia/quality_scale.yaml` records where the
  integration stands on Home Assistant's
  [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
  Update it with the code.
- Bump `version` in `manifest.json`, add the changes to `CHANGELOG.md`, then
  tag `vX.Y.Z` and publish a GitHub release (HACS installs releases).
