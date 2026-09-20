"""Bluetti BT Connect number entities."""

from __future__ import annotations
import asyncio
import logging
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from bluetti_bt_connect_lib import (
    build_device,
    BluettiDevice,
    DeviceField,
    FieldName,
    get_unit,
)

from .types import FullDeviceConfig, get_category
from . import device_info as dev_info, get_unique_id
from .const import DATA_COORDINATOR, DATA_LOCK, DOMAIN, WRITE_SETTLE_SECONDS
from .coordinator import PollingCoordinator
from .utils import mac_loggable, unique_id_logable


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Setup number entities."""

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

    logger.info("Creating number entities for device with address %s", config.address)
    device_info = dev_info(entry)

    bluetti_device = build_device(config.name)

    numbers_to_add = []
    number_fields = bluetti_device.get_number_fields()
    for field in number_fields:
        category = get_category(FieldName(field.name))

        numbers_to_add.append(
            BluettiNumber(
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

    async_add_entities(numbers_to_add)


class BluettiNumber(CoordinatorEntity, NumberEntity):
    """Bluetti universal slider/number entity."""

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

        self._attr_native_min_value = field.min if field.min is not None else 0
        self._attr_native_max_value = field.max if field.max is not None else 100
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_unit_of_measurement = get_unit(FieldName(field.name))

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
        """Set entity as available."""
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
        """Set entity as unavailable."""
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
            self._logger.debug("Data from coordinator is None")
            self._set_unavailable("Data is None")
            return

        if not isinstance(self.coordinator.data, dict):
            self._logger.debug(
                "Invalid data from coordinator (number.%s)",
                unique_id_logable(self._attr_unique_id),
            )
            self._set_unavailable("Invalid data")
            return

        if self._response_key not in self.coordinator.data:
            self._set_unavailable("Field not in data")
            return

        value = self.coordinator.data[self._response_key]
        self._attr_native_value = value
        self._set_available()

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        self._logger.debug(
            "Set %s on %s",
            self._response_key,
            mac_loggable(self._address),
        )
        await self.write_to_device(value)

    async def write_to_device(self, value: float):
        """Write to device and report what it said.

        The write goes through the coordinator's reader, so it travels on the
        connection polling already uses - no second link to race with, and
        the device's Modbus reply is read instead of discarded. Acceptance is
        confirmed by the device now rather than assumed.
        """

        if self.coordinator.connection_released:
            # Released on purpose - writing would take the device
            # straight back from whatever is using it.
            self._logger.warning(
                "Not writing %s - the Bluetooth connection is released until %s",
                self._field.name,
                self.coordinator.release_until,
            )
            return

        result = await self.coordinator.reader.write(self._field.name, int(value))

        self._last_write_result = result

        if not result.accepted:
            self._logger.warning("Write was not confirmed - %s", result)

        # The echo already confirms acceptance; this only lets the register
        # catch up so the read-back shows the new value.
        await asyncio.sleep(WRITE_SETTLE_SECONDS)

        await self.coordinator.async_request_refresh()
