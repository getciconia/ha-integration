#!/usr/bin/env python3
"""End-to-end integration test against a REAL Ciconia account.

Maintainer tool: it signs in to the Ciconia website the way a browser does
(sign-in and approval forms), so it follows that website and may need
updating when its pages change. Not run in this repository's CI.

Spins up a throwaway HA instance in Docker (separate container/network/
config dir from the dev instance in ha-dev.sh - safe to run alongside
it), onboards it headlessly, adds the Ciconia integration via the
actual config flow (over HA's REST API, exactly as a user would through
the UI) - including approving the link code on the Ciconia website
by signing in as the test account - waits for the coordinator's first
successful poll, and asserts on the resulting entities. Always tears the
container down afterward, pass or fail.

This hits the real Ciconia API with real credentials - it's for
on-demand/CI verification that the integration still actually works
against the live backend, not for routine local development (see
bootstrap.py + ha-dev.sh for that).

Usage:
    CICONIA_EMAIL=you@example.com CICONIA_PASSWORD=xxx python3 dev/ha/scripts/integration_test.py

Env vars:
    CICONIA_EMAIL        Required. Sign-in email of a Ciconia account with
                    at least one active device.
    CICONIA_PASSWORD     Required. Its password.
    CICONIA_BASE_URL     Optional. Defaults to the integration's own
                    DEFAULT_BASE_URL (the hosted instance). It must be
                    reachable both from this machine and from inside the
                    HA container.
    HA_PORT         Optional. Host port to publish HA on (default 8181,
                    deliberately different from ha-dev.sh's 8123 so both
                    can run at once).
"""

from __future__ import annotations

from http.cookiejar import CookieJar
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from _ha_api import get_access_token, http, wait_for_ha

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_default_base_url() -> str:
    # Load const.py directly rather than `import custom_components.ciconia.const`
    # - the latter runs custom_components/ciconia/__init__.py first (it's the
    # parent package), which imports homeassistant. const.py itself has zero
    # dependencies, and this script has none either - keep it that way so CI
    # doesn't need a pip install step, just python3 + docker.
    const_path = REPO_ROOT / "custom_components" / "ciconia" / "const.py"
    spec = importlib.util.spec_from_file_location("ciconia_const", const_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DEFAULT_BASE_URL


DEFAULT_BASE_URL = _load_default_base_url()

COMPOSE_FILE = REPO_ROOT / "dev" / "ha" / "docker-compose.yml"
COMPOSE_PROJECT = "ciconia-ha-itest"
CONTAINER_NAME = "ciconia-ha-itest"
HA_PORT = os.environ.get("HA_PORT", "8181")
HA_URL = f"http://localhost:{HA_PORT}"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  OK   {message}")
    else:
        print(f"  FAIL {message}")
        failures.append(message)


def compose(*args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HA_CONTAINER_NAME": CONTAINER_NAME,
        "HA_PORT": HA_PORT,
    }
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", COMPOSE_PROJECT, *args],
        env=env,
        check=True,
    )


def _csrf_token(html: str, action: str, contains: str = "") -> str:
    """The authenticity_token of the form posting to `action` (and holding `contains`)."""
    for form in re.findall(r"<form\b.*?</form>", html, flags=re.DOTALL):
        if f'action="{action}"' in form and contains in form:
            match = re.search(r'name="authenticity_token" value="([^"]+)"', form)
            if match:
                return match.group(1)
    raise SystemExit(f"No form for {action} on the page. Did the sign-in or link page change?")


def approve_link_code(base_url: str, link_url: str, email: str, password: str) -> None:
    """Do what a user does in the browser: open the link, sign in, click Allow."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def post(path: str, fields: dict) -> tuple[str, str]:
        body = urllib.parse.urlencode(fields).encode()
        with opener.open(f"{base_url}{path}", data=body) as resp:
            return resp.geturl(), resp.read().decode()

    with opener.open(link_url) as resp:  # redirects to the sign-in page
        sign_in = resp.read().decode()
    _, page = post(
        "/session",
        {
            "authenticity_token": _csrf_token(sign_in, "/session"),
            "email_address": email,
            "password": password,
        },
    )  # redirects back to the link page
    code = urllib.parse.parse_qs(urllib.parse.urlparse(link_url).query)["code"][0]
    final_url, _ = post(
        "/link",
        {
            "authenticity_token": _csrf_token(page, "/link", 'value="allow"'),
            "code": code,
            "decision": "allow",
        },
    )
    if "/link/approved" not in final_url:
        raise SystemExit(f"Approving the link code didn't succeed (ended at {final_url})")


def create_account_entry(token: str, base_url: str, email: str, password: str) -> str:
    flow = http(
        HA_URL, "POST", "/api/config/config_entries/flow", token=token, data={"handler": "ciconia"}
    )
    flow_id = flow["flow_id"]
    if flow.get("step_id") == "user":  # the server address sits in a folded section
        flow = http(
            HA_URL,
            "POST",
            f"/api/config/config_entries/flow/{flow_id}",
            token=token,
            data={"advanced": {"base_url": base_url}},
        )
    if flow["type"] != "progress":
        raise SystemExit(f"Expected the link-code step, got: {flow}")
    link_url = flow["description_placeholders"]["url"]
    print(f"Approving link code {flow['description_placeholders']['code']} ...")
    approve_link_code(base_url, link_url, email, password)

    # HA moves on by itself once its poll sees the approval.
    deadline = time.monotonic() + 30
    while flow["type"] == "progress" and time.monotonic() < deadline:
        time.sleep(1)
        flow = http(HA_URL, "GET", f"/api/config/config_entries/flow/{flow_id}", token=token)
    if flow.get("step_id") == "devices":  # keep every tracker ticked
        default = next(f["default"] for f in flow["data_schema"] if f["name"] == "devices")
        flow = http(
            HA_URL,
            "POST",
            f"/api/config/config_entries/flow/{flow_id}",
            token=token,
            data={"devices": default},
        )
    if flow["type"] != "create_entry":
        raise SystemExit(f"Config flow failed to complete: {flow}")
    return flow["result"]["entry_id"]


def wait_for_loaded(token: str, entry_id: str, timeout: int = 30) -> str:
    deadline = time.monotonic() + timeout
    state = "unknown"
    while time.monotonic() < deadline:
        entries = http(
            HA_URL, "GET", "/api/config/config_entries/entry?domain=ciconia", token=token
        )
        entry = next(e for e in entries if e["entry_id"] == entry_id)
        state = entry["state"]
        if state != "not_loaded":
            return state
        time.sleep(1)
    return state


def run_assertions(token: str, base_url: str) -> None:
    entry_id = create_account_entry(
        token, base_url, os.environ["CICONIA_EMAIL"], os.environ["CICONIA_PASSWORD"]
    )
    print(f"Config entry created: {entry_id}")

    state = wait_for_loaded(token, entry_id)
    check(state == "loaded", f"config entry state is 'loaded' (was '{state}')")
    if state != "loaded":
        return  # nothing else will be meaningful

    all_states = http(HA_URL, "GET", "/api/states", token=token)
    by_domain: dict[str, list[dict]] = {}
    for s in all_states:
        by_domain.setdefault(s["entity_id"].split(".")[0], []).append(s)

    # A fresh HA has no other device trackers, so these are all ours - one
    # per active device on the account.
    trackers = by_domain.get("device_tracker", [])
    check(len(trackers) >= 1, "at least one device_tracker entity exists")
    if not trackers:
        return  # can't derive the device slugs below without them

    # Our device_tracker is unnamed (_attr_name = None), so its entity_id is
    # exactly the device's slug - e.g. "device_tracker.atm_700_domek" ->
    # "atm_700_domek". Our sensor/binary_sensor entities are always
    # "<domain>.<that slug>_<key>". Use it to filter out unrelated entities
    # a fresh HA instance creates on its own (sensor.sun_*, sensor.backup_*,
    # etc.) so results only cover this integration's own entities.
    slugs = [t["entity_id"].split(".", 1)[1] for t in trackers]
    ours = {
        domain: [
            s
            for s in by_domain.get(domain, [])
            if any(s["entity_id"].startswith(f"{domain}.{slug}_") for slug in slugs)
        ]
        for domain in ("sensor", "binary_sensor")
    }
    ours["device_tracker"] = trackers

    check(len(ours["binary_sensor"]) >= 1, "at least one binary_sensor entity exists")
    check(len(ours["sensor"]) >= 1, "at least one sensor entity exists")

    for entities in ours.values():
        for entity in entities:
            check(entity["state"] != "unavailable", f"{entity['entity_id']} is not unavailable")

    for tracker in trackers:
        check("fixed_time" in tracker["attributes"], f"{tracker['entity_id']} exposes fixed_time")
        check(
            "fix_age_seconds" in tracker["attributes"],
            f"{tracker['entity_id']} exposes fix_age_seconds",
        )

    logs = subprocess.run(
        ["docker", "logs", CONTAINER_NAME],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    ).stdout
    error_lines = [
        line for line in logs.splitlines() if "ERROR" in line and "ciconia" in line.lower()
    ]
    check(not error_lines, "no ERROR-level ciconia log lines")
    for line in error_lines:
        print(f"    {line}")

    print(f"(tested against base_url={base_url}, {len(trackers)} tracker(s))")


def main() -> None:
    if not os.environ.get("CICONIA_EMAIL") or not os.environ.get("CICONIA_PASSWORD"):
        raise SystemExit("CICONIA_EMAIL and CICONIA_PASSWORD must both be set.")
    # `or DEFAULT_BASE_URL` (not .get(..., default)) so an empty-string env
    # var (e.g. an unset workflow_dispatch input passed through as "") also
    # falls back to the default instead of trying to hit an empty URL.
    base_url = os.environ.get("CICONIA_BASE_URL") or DEFAULT_BASE_URL

    tmp = tempfile.mkdtemp(prefix="ciconia-itest-")
    config_dir = Path(tmp) / "config"
    config_dir.mkdir()
    state_file = Path(tmp) / "state.json"
    os.environ["HA_CONFIG_DIR"] = str(config_dir)

    try:
        print(f"Starting throwaway HA on port {HA_PORT} ...")
        compose("up", "-d")
        wait_for_ha(HA_URL)
        token = get_access_token(HA_URL, state_file, "admin", "admin")

        print("Running assertions ...")
        run_assertions(token, base_url)
    finally:
        print("Saving container logs to ha-itest.log ...")
        with open("ha-itest.log", "w") as f:
            subprocess.run(
                ["docker", "logs", CONTAINER_NAME], stdout=f, stderr=subprocess.STDOUT, check=False
            )
        print("Tearing down ...")
        compose("down", "-v")
        # HA (running as root inside the container) creates some files/dirs
        # in the bind-mounted config dir as root, which the CI runner's
        # unprivileged user can't remove directly on Linux - clean those up
        # via a container running with the same privilege that created them,
        # then a plain (best-effort) rmtree for whatever's left.
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{config_dir}:/cleanup",
                "--entrypoint",
                "sh",
                "ghcr.io/home-assistant/home-assistant:stable",
                "-c",
                "rm -rf /cleanup/* /cleanup/.[!.]*",
            ],
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s) failed")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("PASSED: all assertions passed")


if __name__ == "__main__":
    main()
