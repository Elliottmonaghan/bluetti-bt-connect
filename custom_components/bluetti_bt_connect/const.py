"""Constants for the Bluetti BT Connect integration."""

DOMAIN = "bluetti_bt_connect"
MANUFACTURER = "Bluetti"

CONF_OPTIONS = "options"

DATA_COORDINATOR = "coordinator"
DATA_LOCK = "lock"
DATA_CONNECTION = "connection"

CONNECTION_KEEP_ALIVE_SECONDS = -1
"""How long the shared BLE connection is held open after a conversation.

Negative holds it indefinitely, which is the point: connection setup stops
happening on every poll, and a write lands on a link that is already up.

The cost is that the device accepts one central at a time, so while this is
held the Bluetti phone app cannot connect. The "Hold Bluetooth connection"
switch releases it on demand, and puts itself back after
CONNECTION_RELEASE_SECONDS so a forgotten release cannot leave the
integration dead.

A positive value instead drops the link that many seconds after each
conversation - 0 restores the original connect-per-poll behaviour.
"""

CONNECTION_RELEASE_SECONDS = 300
"""How long a released connection stays released before resuming on its own.

Long enough to do something useful in the Bluetti app, short enough that
forgetting to switch it back costs one gap in the data rather than all of
it.
"""

WRITE_SETTLE_SECONDS = 2
"""Pause between a write and the refresh that reads it back.

This was 5 seconds when a write had no confirmation and the read-back was
the only evidence anything had happened. The Modbus echo now confirms
acceptance directly, so this only exists to let the register catch up
before the entity re-reads it. Raise it if entity state looks stale after
a change.
"""
