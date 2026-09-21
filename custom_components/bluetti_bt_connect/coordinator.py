"""Coordinator for Bluetti integration."""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
import logging
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from bluetti_bt_connect_lib import (
    build_device,
    DeviceConnection,
    DeviceReader,
    DeviceReaderConfig,
    FieldName,
)

from .utils import mac_loggable
from .types import FullDeviceConfig
from homeassistant.util import dt as dt_util

from .const import CONNECTION_KEEP_ALIVE_SECONDS, CONNECTION_RELEASE_SECONDS


class PollingCoordinator(DataUpdateCoordinator):
    """Polling coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: FullDeviceConfig,
        lock: asyncio.Lock,
        connection: DeviceConnection | None = None,
    ):
        """Initialize coordinator."""
        super().__init__(
            hass,
            logging.getLogger(
                f"{__name__}.{mac_loggable(config.address).replace(':', '_')}"
            ),
            name="Bluetti polling coordinator",
            update_interval=timedelta(seconds=config.polling_interval),
        )

        self.config = config
        self.connection = connection
        self.reader = None

        self.release_until: datetime | None = None
        """When a deliberate release expires, or None while holding.

        The connection is held open permanently, so something has to be able
        to let go of it - the device accepts one central at a time and the
        Bluetti app is locked out until we do. Polling is suspended for the
        duration, otherwise the next poll would immediately reconnect and
        take the device back.
        """

        # Create client
        self.logger.info("Creating client for %s", config.name)
        bluetti_device = build_device(config.name)

        if bluetti_device is None:
            self.logger.error("Device is unknown type: %s", config.name)
            return

        self.reader = DeviceReader(
            config.address,
            bluetti_device,
            self.hass.loop.create_future,
            DeviceReaderConfig(
                config.polling_timeout,
                config.use_encryption,
                keep_alive_seconds=CONNECTION_KEEP_ALIVE_SECONDS,
                unlock_password=config.bt_password,
            ),
            lock,
            connection=connection,
        )

    @property
    def connection_released(self) -> bool:
        """Whether the connection is currently released for something else."""
        return self.release_until is not None and dt_util.utcnow() < self.release_until

    async def async_release_connection(
        self, seconds: int = CONNECTION_RELEASE_SECONDS
    ) -> None:
        """Drop the connection and stay off the device for a while.

        Resumption is not on a timer of its own - the next scheduled poll
        after the window expires simply reconnects. One less thing to cancel,
        and nothing left running if the entry unloads meanwhile.
        """
        self.release_until = dt_util.utcnow() + timedelta(seconds=seconds)
        self.logger.info(
            "Releasing the Bluetooth connection until %s", self.release_until
        )

        if self.connection is not None:
            await self.connection.disconnect()

    async def async_hold_connection(self) -> None:
        """Resume immediately, before the release window is up."""
        if self.release_until is None:
            return

        self.release_until = None
        self.logger.info("Resuming the Bluetooth connection")
        await self.async_request_refresh()

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        if self.connection_released:
            # Deliberately off the device. Keep the last reading rather than
            # marking everything unavailable - the data is stale, not gone,
            # and this is a state the user asked for.
            self.logger.debug("Connection released until %s", self.release_until)

            if self.data is None:
                raise UpdateFailed("Bluetooth connection released")

            return self.data

        if self.release_until is not None:
            self.logger.info("Release window expired, reconnecting")
            self.release_until = None

        # Check the device is reachable before trying to talk to it.
        #
        # async_address_present() answers from advertisement history, so it
        # only means anything while we are NOT connected: a BLE peripheral
        # generally stops advertising once a central is attached, so on a
        # held-open connection the last advertisement eventually goes stale
        # and this returns False for a device that is right there and
        # answering us. Skip the check whenever we already hold a live
        # connection - that connection is the better liveness signal, and a
        # link that has actually dropped surfaces as a read failure below.
        if self.reader is None or not self.reader.is_connected:
            if (
                bluetooth.async_address_present(
                    self.hass, self.config.address, connectable=True
                )
                is False
            ):
                self.logger.warning("Device not connected")
                raise UpdateFailed("Device not connected")

        if self.reader is None:
            self.logger.error(
                "Reader not initialized - device type may be unsupported: %s",
                self.config.name,
            )
            raise UpdateFailed(
                f"Reader not initialized - device type may be unsupported: {self.config.name}"
            )

        data = await self.reader.read()
        if data is None:
            raise UpdateFailed("Error while reading data from device")

        # Computed, not read from any device register: the existing
        # "Total AC Power" register was found (July 28) to actually report
        # |P1| + |P2| + |P3| - an unsigned magnitude, not a true net
        # directional figure. That was fixed with a properly-signed
        # P1+P2+P3 sum (previously exposed as "True AC Total Power (Net)").
        #
        # That sign fix alone isn't the full picture, though - a signed
        # AC total still conflates the battery's own charge/discharge
        # activity with whatever the PV strings are contributing at the
        # same moment. During any period with solar production (which
        # routinely overlaps with a scheduled grid-import/charging
        # window), AC total alone overstates how hard the battery itself
        # is actually charging or discharging.
        #
        # The correct formula, worked out and confirmed in an earlier
        # session: Battery net = AC_total - PV. Grid/export figures were
        # deliberately tested and excluded from this formula - including
        # them double-counts export power that's already folded into
        # AC_total in some operating modes.
        #
        # Sign convention: positive = battery discharging (AC output
        # exceeds what solar alone is providing), negative = battery
        # charging (AC total is less than solar, or negative outright,
        # meaning grid/solar power is flowing into the battery).
        p1 = data.get(FieldName.AC_P1_POWER.value)
        p2 = data.get(FieldName.AC_P2_POWER.value)
        p3 = data.get(FieldName.AC_P3_POWER.value)
        pv = data.get(FieldName.TOTAL_PV_POWER.value)
        if p1 is not None and p2 is not None and p3 is not None and pv is not None:
            data[FieldName.BATTERY_NET_POWER.value] = (p1 + p2 + p3) - pv

        return data
