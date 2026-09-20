"""Bluetti Bluetooth Integration"""

from __future__ import annotations
import asyncio
import re
import logging
from typing import List
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import ConfigEntryNotReady

from .utils import mac_loggable
from bluetti_bt_connect_lib import DeviceConnection

from .const import (
    DATA_CONNECTION,
    DATA_COORDINATOR,
    DATA_LOCK,
    DOMAIN,
    MANUFACTURER,
)
from .types import FullDeviceConfig
from .coordinator import PollingCoordinator

PLATFORMS: List[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bluetti Powerstation from a config entry."""

    config = FullDeviceConfig.from_dict(entry.data)

    if config is None:
        logging.getLogger(__name__).error(
            "Failed to parse config entry data for '%s'. "
            "This may happen when upgrading from v0.1.6 to v0.2.x "
            "due to missing 'use_encryption' field.",
            entry.title,
        )
        return False

    logger = logging.getLogger(
        f"{__name__}.{mac_loggable(config.address).replace(':', '_')}"
    )

    logger.debug("Init Bluetti BT Integration")

    if not bluetooth.async_address_present(hass, config.address):
        raise ConfigEntryNotReady("Bluetti device not present")

    # Create data structure
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    # One lock, so polls and writes never overlap on the device.
    lock = asyncio.Lock()

    # One connection, shared by polling and every control. Previously each
    # write opened its own link, which could tear down the connection a poll
    # was using and cost two connect cycles per button press.
    #
    # The device lookup is handed to the library as a callable so it can use
    # Home Assistant's own cache, which answers instantly and picks the best
    # proxy path, instead of running a five-second scan of its own.
    def ble_device():
        return bluetooth.async_ble_device_from_address(
            hass, config.address, connectable=True
        )

    connection = DeviceConnection(config.address, device_provider=ble_device)

    # Create coordinator for polling
    logger.debug("Creating coordinator")
    coordinator = PollingCoordinator(
        hass,
        config,
        lock,
        connection,
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id].setdefault(DATA_COORDINATOR, coordinator)
    hass.data[DOMAIN][entry.entry_id].setdefault(DATA_LOCK, lock)
    hass.data[DOMAIN][entry.entry_id].setdefault(DATA_CONNECTION, connection)

    logger.debug("Creating entities")
    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    logger.debug("Setup done")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down the entry, releasing the BLE connection.

    Without this the shared connection outlives a reload: the link stays up,
    keeps consuming one of the proxy's connection slots, and keeps the
    Bluetti phone app locked out, while a second connection is built
    alongside it on the next setup.
    """

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if not unloaded:
        return False

    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    connection = data.get(DATA_CONNECTION)

    if connection is not None:
        await connection.disconnect()

    return True


def device_info(entry: ConfigEntry):
    """Device info."""
    config = FullDeviceConfig.from_dict(entry.data)

    if config is None:
        return None

    return DeviceInfo(
        identifiers={(DOMAIN, config.address)},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model=config.dev_type,
    )


def get_unique_id(name: str, sensor_type: str | None = None):
    """Generate an unique id."""
    res = re.sub("[^A-Za-z0-9]+", "_", name).lower()
    if sensor_type is not None:
        return f"{sensor_type}.{res}"
    return res
