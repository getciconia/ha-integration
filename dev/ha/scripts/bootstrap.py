#!/usr/bin/env python3
"""Headlessly complete HA onboarding for the dev container - no clicking
through the UI. Does NOT add Ciconia; do that in the UI and link your own
Ciconia account with a code.

(See integration_test.py for a fully automated, real-device end-to-end
check that DOES add a device - that one's for CI/on-demand verification,
this one's for manual poking-around in the browser.)

Idempotent: safe to re-run. Onboarding only happens once per HA config
dir - the admin account's refresh_token is cached in .dev-state.json
(gitignored, sibling to this script's parent dir) so re-runs just print
the same login details again instead of re-onboarding.

Usage:
    python3 bootstrap.py

Env vars:
    HA_URL                                Base URL of the dev HA instance
                                           (default http://localhost:8123)
    DEV_HA_USERNAME / DEV_HA_PASSWORD     Admin user created on first run
                                           (defaults: admin / admin - this
                                           instance is localhost-only, so
                                           ease of typing wins over strength)
"""

from __future__ import annotations

import os
from pathlib import Path

from _ha_api import onboard, wait_for_ha

HA_URL = os.environ.get("HA_URL", "http://localhost:8123").rstrip("/")
STATE_FILE = Path(__file__).resolve().parent.parent / ".dev-state.json"


def main() -> None:
    wait_for_ha(HA_URL)
    username = os.environ.get("DEV_HA_USERNAME", "admin")
    password = os.environ.get("DEV_HA_PASSWORD", "admin")
    state = onboard(HA_URL, STATE_FILE, username, password)

    print()
    print("=" * 50)
    print(f"  URL:      {HA_URL}")
    print(f"  Username: {state['username']}")
    print(f"  Password: {state['password']}")
    print("=" * 50)
    print()
    print(
        "The Ciconia integration's code is already installed (live-mounted "
        "from custom_components/ciconia) but not set up yet. Log in above, "
        "then: Settings -> Devices & Services -> Add Integration -> Ciconia "
        "and link your Ciconia account."
    )


if __name__ == "__main__":
    main()
