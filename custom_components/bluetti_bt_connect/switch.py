"""Bluetti BT switches."""

from __future__ import annotations
import asyncio
import logging
import async_timeout
from bleak import BleakScanner
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from bluetti_bt_connect_lib import (
    build_device,
    BluettiDevice,
    DeviceField,
    FieldName,
)
from bluetti_bt_connect_lib.registers import WriteableRegister, ReadableRegisters
from bluetti_bt_connect_lib.const import WRITE_UUID, NOTIFY_UUID

from .types import FullDeviceConfig, get_category
from . import device_info as dev_info, get_unique_id
from .const import DATA_COORDINATOR, DATA_LOCK, DOMAIN
from .coordinator import PollingCoordinator
from .utils import mac_loggable, unique_id_logable


# Register 21000 was observed in the official app's own Bluetooth traffic,
# written repeatedly (~once per second) the entire time the Settings screen
# is open - a "presence" heartbeat, not tied to any specific toggle action.
#
# Direct log analysis (July 27) showed a previously-pending HA write to
# grid export actually take effect ~8-9 seconds into a *fresh* app
# connection, with no write to register 2208 anywhere near that moment -
# strongly suggesting the trigger isn't the keep-alive write specifically,
# but a period of sustained, successful two-way communication (the app
# continuously reads many registers throughout this whole window, not just
# writing 21000). The pure keep-alive-only version (repeated writes, no
# reads) was tested live and did not resolve the issue.
#
# This version adds real register reads during the warm-up period,
# reusing the existing connection via DeviceReader's ble_client parameter,
# to more faithfully replicate what the app actually does. Still an
# unverified hypothesis, scoped narrowly to this one field - every other
# switch has worked reliably without any of this, and we don't want to
# change behavior for anything that already works.
SETTINGS_KEEPALIVE_REGISTER = 21000
# The exact sequence observed, in order, across every capture analyzed
# (July 27-28, including a full airplane-mode test confirming this is
# entirely Bluetooth-local, no internet dependency involved): six specific
# reads, always in this order, followed by a single write to register
# 21000. In the one capture where a pending HA write was independently
# confirmed to commit (log5.pklg), it did so in the ~0.9 second window
# immediately after this exact sequence completed.
SETTINGS_WARMUP_READS = [
    (1, 16),
    (100, 93),
    (2000, 94),
    (2200, 105),
    (6000, 42),
    (6100, 104),
]
SETTINGS_WARMUP_READ_TIMEOUT_SECONDS = 5

# After the initial sequence + keep-alive write, the app doesn't just stop
# and write - it continues its normal ~1/sec polling loop (a narrower
# subset: 100, 2000, 2200, 6000, 6100 - no register 1, no 21000 again) for
# several more seconds before any further action. This replicates that
# sustained activity rather than jumping straight to the write immediately
# after the one-shot sequence, in case the device expects continued
# activity rather than just the initial handshake alone.
SETTINGS_POLLING_CYCLE = [(100, 93), (2000, 94), (2200, 105), (6000, 42), (6100, 104)]
SETTINGS_POLLING_CYCLE_REPEATS = 5

FIELDS_REQUIRING_KEEPALIVE = {FieldName.GRID_EXPORT_ENABLED.value}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Setup switch entities."""

    config = FullDeviceConfig.from_dict(entry.data)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    lock = hass.data[DOMAIN][entry.entry_id][DATA_LOCK]

    logger = logging.getLogger(
        f"{__name__}.{mac_loggable(config.address).replace(':', '_')}"
    )

    if config.use_encryption is True:
        logger.info("Controls are disabled on encrypted devices")
        return None

    if config is None or not isinstance(coordinator, PollingCoordinator):
        logger.error("No coordinator found")
        return None

    # Generate device info
    logger.info("Creating switches for device with address %s", config.address)
    device_info = dev_info(entry)

    # Add switches
    bluetti_device = build_device(config.name)

    switches_to_add = []
    switch_fields = bluetti_device.get_switch_fields()
    for field in switch_fields:
        category = get_category(FieldName(field.name))

        switches_to_add.append(
            BluettiSwitch(
                bluetti_device,
                config.address,
                coordinator,
                device_info,
                field,
                lock,
                category=category,
                logger=logger,
            )
        )

    async_add_entities(switches_to_add)


class BluettiSwitch(CoordinatorEntity, SwitchEntity):
    """Bluetti universal switch."""

    def __init__(
        self,
        bluetti_device: BluettiDevice,
        address: str,
        coordinator: PollingCoordinator,
        device_info: DeviceInfo,
        field: DeviceField,
        lock: asyncio.Lock,
        category: EntityCategory | None = None,
        logger: logging.Logger = logging.getLogger(),
    ):
        """Init entity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._logger = logger

        e_name = f"{device_info.get('name')} {field.name}"
        self._bluetti_device = bluetti_device
        self._address = address
        self._field = field
        self._response_key = field.name
        self._unavailable_counter = 5
        self._lock = lock

        self._attr_has_entity_name = True
        self._attr_device_info = device_info
        self._attr_translation_key = field.name
        self._attr_available = False
        self._attr_unique_id = get_unique_id(e_name)
        self._attr_entity_category = category

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._attr_available

    def _set_available(self):
        """Set switch as available."""
        self._attr_available = True
        self._unavailable_counter = 0
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()

    def _set_unavailable(self, cause: str = "Unknown"):
        """Set switch as unavailable."""
        self._unavailable_counter += 1

        self._attr_extra_state_attributes = {
            "unavailable_counter": self._unavailable_counter,
            "unavailable_cause": cause,
        }

        if self._unavailable_counter >= 5:
            self._attr_available = False

        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        if self.coordinator.data is None:
            self._logger.debug(
                "Data from coordinator is None",
            )
            self._set_unavailable("Data is None")
            return

        self._logger.debug(
            "Updating state of %s", unique_id_logable(self._attr_unique_id)
        )
        if not isinstance(self.coordinator.data, dict):
            self._logger.debug(
                "Invalid data from coordinator (switch.%s)",
                unique_id_logable(self._attr_unique_id),
            )
            self._set_unavailable("Invalid data")
            return

        response_data = self.coordinator.data.get(self._response_key)
        if response_data is None:
            self._set_unavailable("No data")
            return

        if not isinstance(response_data, bool):
            self._logger.warning(
                "Invalid response data type from coordinator (switch.%s): %s",
                unique_id_logable(self._attr_unique_id),
                response_data,
            )
            self._set_unavailable("Invalid data type")
            return

        self._set_available()
        self._attr_is_on = response_data is True
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        self._logger.debug(
            "Turn on %s on %s", self._response_key, mac_loggable(self._address)
        )
        await self.write_to_device(True)

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        self._logger.debug(
            "Turn off %s on %s", self._response_key, mac_loggable(self._address)
        )
        await self.write_to_device(False)

    async def write_to_device(self, state: bool):
        """Write to device."""

        try:
            device = await BleakScanner.find_device_by_address(self._address, timeout=5)

            if device is None:
                return

            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                device.name or "Unknown Device",
                max_attempts=10,
            )

            if not client.is_connected:
                return

            needs_keepalive = self._response_key in FIELDS_REQUIRING_KEEPALIVE

            # Everything below runs under one lock acquisition and one
            # continuous connection, so the warm-up reads, keep-alive
            # writes, and the actual write can never be split apart by the
            # polling coordinator stepping in between them, and the
            # connection is never disconnected until we're fully done.
            async with self._lock:
                async with async_timeout.timeout(45):
                    try:
                        if needs_keepalive:
                            self._logger.debug(
                                "Replaying observed connection sequence before writing %s",
                                self._response_key,
                            )

                            notify_future: asyncio.Future | None = None

                            def _on_notify(_: int, data: bytearray):
                                if notify_future is not None and not notify_future.done():
                                    notify_future.set_result(bytes(data))

                            await client.start_notify(NOTIFY_UUID, _on_notify)

                            for addr, qty in SETTINGS_WARMUP_READS:
                                notify_future = self.hass.loop.create_future()
                                read_cmd = ReadableRegisters(addr, qty)
                                await client.write_gatt_char(
                                    WRITE_UUID, bytes(read_cmd)
                                )
                                try:
                                    async with async_timeout.timeout(
                                        SETTINGS_WARMUP_READ_TIMEOUT_SECONDS
                                    ):
                                        await notify_future
                                except TimeoutError:
                                    self._logger.debug(
                                        "Warm-up read of address %s timed out, continuing anyway",
                                        addr,
                                    )

                            await client.stop_notify(NOTIFY_UUID)

                            self._logger.debug(
                                "Sending settings keep-alive write before writing %s",
                                self._response_key,
                            )
                            keepalive_cmd = WriteableRegister(
                                SETTINGS_KEEPALIVE_REGISTER, 1
                            )
                            await client.write_gatt_char(
                                WRITE_UUID, bytes(keepalive_cmd)
                            )

                            self._logger.debug(
                                "Continuing normal polling cycle before writing %s, "
                                "matching the app's sustained behavior",
                                self._response_key,
                            )
                            await client.start_notify(NOTIFY_UUID, _on_notify)
                            for _ in range(SETTINGS_POLLING_CYCLE_REPEATS):
                                for addr, qty in SETTINGS_POLLING_CYCLE:
                                    notify_future = self.hass.loop.create_future()
                                    read_cmd = ReadableRegisters(addr, qty)
                                    await client.write_gatt_char(
                                        WRITE_UUID, bytes(read_cmd)
                                    )
                                    try:
                                        async with async_timeout.timeout(
                                            SETTINGS_WARMUP_READ_TIMEOUT_SECONDS
                                        ):
                                            await notify_future
                                    except TimeoutError:
                                        self._logger.debug(
                                            "Polling-cycle read of address %s timed out, continuing anyway",
                                            addr,
                                        )
                            await client.stop_notify(NOTIFY_UUID)

                        command = self._bluetti_device.build_write_command(
                            self._field.name, state
                        )
                        if command is None:
                            self._logger.error("Field is not writeable")
                            return

                        self._logger.debug("Writing command: %s", command)
                        await client.write_gatt_char(WRITE_UUID, bytes(command))
                        self._logger.debug("Write successful")

                        # Wait until device has changed value, otherwise
                        # reading register might reset it
                        await asyncio.sleep(5)
                    finally:
                        await client.disconnect()

        except TimeoutError:
            self._logger.error("Timed out for device %s", mac_loggable(self._address))
            return None

        await self.coordinator.async_request_refresh()
