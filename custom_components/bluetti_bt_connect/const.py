"""Constants for the Bluetti BT Connect integration."""

DOMAIN = "bluetti_bt_connect"
MANUFACTURER = "Bluetti"

CONF_OPTIONS = "options"

DATA_COORDINATOR = "coordinator"
DATA_LOCK = "lock"
DATA_CONNECTION = "connection"

WRITE_KEEP_ALIVE_SECONDS = 10
"""How long the shared BLE connection is held open after a conversation.

The device accepts one central at a time, so a permanently held link locks
out the Bluetti phone app - which the README still tells you to use when
verifying grid settings. Ten seconds is chosen to span a write and the
refresh that follows it, so those share one connection, while still
dropping the link well inside the polling interval.

Raise it above the polling interval to keep the connection up permanently
and remove connection setup from every poll. That is faster, and it costs
you the phone app while Home Assistant is running.
"""

WRITE_SETTLE_SECONDS = 2
"""Pause between a write and the refresh that reads it back.

This was 5 seconds when a write had no confirmation and the read-back was
the only evidence anything had happened. The Modbus echo now confirms
acceptance directly, so this only exists to let the register catch up
before the entity re-reads it. Raise it if entity state looks stale after
a change.
"""
