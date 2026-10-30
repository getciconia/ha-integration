"""Shared REST-API helpers for driving a real HA instance headlessly.

Used by both bootstrap.py (manual dev instance) and integration_test.py
(ephemeral CI/on-demand instance) — same onboarding dance, different
lifecycle around it.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


def http(
    ha_url: str, method: str, path: str, token: str | None = None, data: dict | None = None
) -> dict:
    url = f"{ha_url}{path}"
    headers = {}
    body = None
    if data is not None:
        if path == "/auth/token":  # the only form-encoded (OAuth2 token) endpoint
            body = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in data.items()).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read()
        print(f"  ! {method} {path} -> {err.code}: {raw.decode(errors='replace')}", file=sys.stderr)
        raise


def wait_for_ha(ha_url: str, timeout: int = 90) -> None:
    print(f"Waiting for HA at {ha_url} ...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # Not /api/onboarding: that endpoint is unloaded entirely once
            # onboarding is fully complete (permanent 404 afterward, not
            # "not ready yet") — manifest.json is a static frontend asset
            # that's always served, onboarded or not.
            http(ha_url, "GET", "/manifest.json")
            print("HA is up.")
            return
        except OSError:
            # Covers urllib.error.URLError/HTTPError (both are OSError
            # subclasses) as well as raw connection errors during
            # startup (ConnectionResetError/ConnectionRefusedError) that
            # aren't wrapped in URLError.
            time.sleep(2)
    raise SystemExit(f"HA didn't come up at {ha_url} within {timeout}s")


def onboard(ha_url: str, state_file: Path, username: str, password: str) -> dict:
    """Create the admin user and finish onboarding on first run; on later
    runs (state_file already has a refresh_token), just confirm it still
    works. Returns {"username", "password", "refresh_token"}."""
    client_id = f"{ha_url}/"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}

    if "refresh_token" in state:
        http(
            ha_url,
            "POST",
            "/auth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": state["refresh_token"],
                "client_id": client_id,
            },
        )
        print("HA already onboarded (reusing saved admin user).")
        return state

    onboarding = http(ha_url, "GET", "/api/onboarding")
    user_step_done = next(s["done"] for s in onboarding if s["step"] == "user")
    if user_step_done:
        raise SystemExit(
            "HA is already onboarded but no saved credentials were found "
            f"({state_file} is missing) — onboarded some other way. Wipe "
            "its config dir and retry."
        )

    print(f"Onboarding HA: creating admin user '{username}' ...")
    resp = http(
        ha_url,
        "POST",
        "/api/onboarding/users",
        data={
            "client_id": client_id,
            "name": "Dev",
            "username": username,
            "password": password,
            "language": "en",
        },
    )
    token_resp = http(
        ha_url,
        "POST",
        "/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": resp["auth_code"],
            "client_id": client_id,
        },
    )
    access_token = token_resp["access_token"]

    http(ha_url, "POST", "/api/onboarding/core_config", token=access_token)
    http(ha_url, "POST", "/api/onboarding/analytics", token=access_token)
    http(
        ha_url,
        "POST",
        "/api/onboarding/integration",
        token=access_token,
        data={"client_id": client_id, "redirect_uri": f"{ha_url}/?auth_callback=1"},
    )

    state = {
        "refresh_token": token_resp["refresh_token"],
        "username": username,
        "password": password,
    }
    state_file.write_text(json.dumps(state, indent=2))
    print("Onboarding complete.")
    return state


def get_access_token(ha_url: str, state_file: Path, username: str, password: str) -> str:
    """onboard() + exchange for a fresh, short-lived access token."""
    onboard(ha_url, state_file, username, password)
    client_id = f"{ha_url}/"
    resp = http(
        ha_url,
        "POST",
        "/auth/login_flow",
        data={
            "client_id": client_id,
            "handler": ["homeassistant", None],
            "redirect_uri": f"{ha_url}/?auth_callback=1",
        },
    )
    resp = http(
        ha_url,
        "POST",
        f"/auth/login_flow/{resp['flow_id']}",
        data={"username": username, "password": password, "client_id": client_id},
    )
    token_resp = http(
        ha_url,
        "POST",
        "/auth/token",
        data={"grant_type": "authorization_code", "code": resp["result"], "client_id": client_id},
    )
    return token_resp["access_token"]
