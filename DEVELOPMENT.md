# Development

## Set up and run the checks

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

## A Home Assistant to try it in (Docker)

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

## End-to-end test (maintainers)

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

## Releasing

- CI runs hassfest and the HACS check on every push.
- `custom_components/ciconia/quality_scale.yaml` records where the
  integration stands on Home Assistant's
  [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
  Update it with the code.
- Bump `version` in `manifest.json`, add the changes to `CHANGELOG.md`, then
  tag `vX.Y.Z` and publish a GitHub release (HACS installs releases).
