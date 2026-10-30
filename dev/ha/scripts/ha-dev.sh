#!/usr/bin/env bash
# Lifecycle helper for the local dev Home Assistant instance (Docker).
# The integration's source is bind-mounted read-only into the container
# from ../../custom_components/ciconia, so `up`/`restart` is all you
# need after editing code - no manual copy/upload step.
set -euo pipefail

cd "$(dirname "$0")/.."

case "${1:-}" in
  up)
    docker compose up -d
    python3 scripts/bootstrap.py
    ;;
  down)
    docker compose down
    ;;
  restart)
    # Custom integration code is only re-imported on a full restart.
    docker compose restart homeassistant
    ;;
  logs)
    docker compose logs -f homeassistant
    ;;
  reset)
    read -r -p "This wipes all local HA state (config/), including any devices you set up. Continue? [y/N] " ans
    if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
      docker compose down
      rm -rf ./config ./.dev-state.json
      mkdir -p ./config
      echo "Wiped. Run 'ha-dev.sh up' to start fresh."
    fi
    ;;
  test)
    # Real end-to-end check against a real account - spins up its own
    # throwaway HA instance (separate from the one above), safe to run
    # while `up` is already running. Requires CICONIA_EMAIL/CICONIA_PASSWORD,
    # loaded from .env (gitignored) if present, else from the environment.
    if [[ -f .env ]]; then
      set -a; source .env; set +a
    fi
    python3 scripts/integration_test.py
    ;;
  *)
    echo "Usage: $0 {up|down|restart|logs|reset|test}"
    exit 1
    ;;
esac
