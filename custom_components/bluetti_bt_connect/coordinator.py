"""Coordinator for Bluetti integration."""

from __future__ import annotations
import asyncio
from datetime import timedelta
import logging
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from bluetti_bt_connect_lib import build_device, DeviceReader, DeviceReaderConfig, FieldName

from .utils import mac_loggable
from .types import FullDeviceConfig


class PollingCoordinator(DataUpdateCoordinator):
    """Polling coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: FullDeviceConfig,
        lock: asyncio.Lock,
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
        self.reader = None

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
            ),
            lock,
        )

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        # Check if device is connected
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
