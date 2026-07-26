"""Coordinator for Bluetti integration."""

from __future__ import annotations
import asyncio
from datetime import timedelta
import logging
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from bluetti_bt_connect_lib import build_device, DeviceReader, DeviceReaderConfig

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

        return data
