"""Constants for the Ciconia integration."""

DOMAIN = "ciconia"
MANUFACTURER = "Ciconia"

CONF_BASE_URL = "base_url"

# One config entry per account (created by linking): the account's stable id
# from the link response, its email for the entry title, and the devices the
# user unticked. Every other device on the account is tracked — including
# ones added later, so a newly activated tracker shows up without any setup.
CONF_ACCOUNT_ID = "account_id"
CONF_ACCOUNT_EMAIL = "account_email"
CONF_EXCLUDED_DEVICES = "excluded_devices"

# Folded away under "Advanced" in the setup form, for development against
# another server. Changed later with Reconfigure (which links again).
DEFAULT_BASE_URL = "https://app.getciconia.com"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 5

# How long since the last fix before the device is considered "stale"
# (binary_sensor.py). Configurable via the options flow — a car
# polled every 30s and a battery-saving pet tracker that sleeps for hours
# need very different definitions of "hasn't reported in a while".
CONF_STALE_AFTER_SECONDS = "stale_after_seconds"
DEFAULT_STALE_AFTER_SECONDS = 3600
MIN_STALE_AFTER_SECONDS = 60

REQUEST_TIMEOUT_SECONDS = 10
