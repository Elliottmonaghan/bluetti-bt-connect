"""Bluetti BT switches."""

from __future__ import annotations
import asyncio
import logging
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

from .types import FullDeviceConfig, get_category
from . import device_info as dev_info, get_unique_id
from .const import (
    CONNECTION_RELEASE_SECONDS,
    DATA_COORDINATOR,
    DATA_LOCK,
    DOMAIN,
    WRITE_SETTLE_SECONDS,
)
from .coordinator import PollingCoordinator
from .utils import mac_loggable, unique_id_logable


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

    logger.info("Creating switches for device with address %s", config.address)
    device_info = dev_info(entry)

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

    switches_to_add.append(
        BluettiConnectionHoldSwitch(coordinator, device_info, logger)
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
        self._last_write_result = None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._attr_available

    def _set_available(self):
        """Set switch as available."""
        self._attr_available = True
        self._unavailable_counter = 0
        self._attr_extra_state_attributes = self._write_attributes()
        self.async_write_ha_state()

    def _write_attributes(self) -> dict:
        """Expose the device's verdict on the last write.

        Previously a rejected write was indistinguishable from an accepted
        one. Surfacing it here means a control that silently does nothing
        says so, in the place someone would look.
        """
        result = self._last_write_result

        if result is None:
            return {}

        attributes = {"last_write": result.outcome.value}

        if result.exception_code is not None:
            attributes["last_write_exception"] = (
                f"0x{result.exception_code:02x} ({result.exception_meaning})"
            )

        return attributes

    def _set_unavailable(self, cause: str = "Unknown"):
        """Set switch as unavailable."""
        self._unavailable_counter += 1

        self._attr_extra_state_attributes = {
            **self._write_attributes(),
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
        """Write to device and report what it said.

        The write goes through the coordinator's reader, so it travels on the
        connection polling already uses - no second link to race with, and
        the device's Modbus reply is read instead of discarded. Acceptance is
        confirmed by the device now rather than assumed.
        """

        if self.coordinator.connection_released:
            # The connection was handed over on purpose. Writing would take
            # it straight back and boot whatever is using it, which is not
            # what someone flicking a switch expects to happen.
            self._logger.warning(
                "Not writing %s - the Bluetooth connection is released until %s",
                self._field.name,
                self.coordinator.release_until,
            )
            return

        result = await self.coordinator.reader.write(self._field.name, state)

        self._last_write_result = result

        if not result.accepted:
            self._logger.warning("Write was not confirmed - %s", result)

        # The echo already confirms acceptance; this only lets the register
        # catch up so the read-back shows the new value.
        await asyncio.sleep(WRITE_SETTLE_SECONDS)

        await self.coordinator.async_request_refresh()


class BluettiConnectionHoldSwitch(CoordinatorEntity, SwitchEntity):
    """Holds or releases the shared Bluetooth connection.

    The connection is kept open permanently so polls and writes do not pay
    for setup each time. The device only accepts one central, so while it is
    held the Bluetti phone app cannot connect - and the app is still the only
    way to independently verify a grid setting actually took.

    Turning this off hands the device back. It turns itself on again after
    CONNECTION_RELEASE_SECONDS, so forgetting costs one gap in the data
    rather than silently killing the integration.
    """

    _attr_has_entity_name = True
    _attr_name = "Hold Bluetooth connection"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: PollingCoordinator,
        device_info: DeviceInfo,
        logger: logging.Logger = logging.getLogger(),
    ):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._logger = logger

        self._attr_device_info = device_info
        self._attr_unique_id = get_unique_id(
            f"{device_info.get('name')} hold bluetooth connection"
        )

    @property
    def available(self) -> bool:
        # Deliberately always available: this is how you get the connection
        # back, so it must still work when everything else has gone stale.
        return True

    @property
    def is_on(self) -> bool:
        return not self.coordinator.connection_released

    @property
    def extra_state_attributes(self) -> dict:
        connection = self.coordinator.connection

        attributes = {
            "connected": connection.is_connected if connection is not None else False,
        }

        if self.coordinator.release_until is not None:
            attributes["resumes_at"] = self.coordinator.release_until.isoformat()

        return attributes

    async def async_turn_on(self, **kwargs):
        """Take the connection back and resume polling now."""
        await self.coordinator.async_hold_connection()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Hand the device over - to the Bluetti app, or anything else."""
        await self.coordinator.async_release_connection(CONNECTION_RELEASE_SECONDS)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
