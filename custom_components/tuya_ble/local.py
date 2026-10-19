"""Credentials of Tuya BLE devices stored locally, without any cloud access."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_ID
from homeassistant.core import HomeAssistant

from .const import (
    AUTH_METHOD_MANUAL,
    CONF_AUTH_METHOD,
    CONF_CATEGORY,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_MODEL,
    CONF_PRODUCT_NAME,
    CONF_UUID,
)
from .tuya_ble import AbstaractTuyaBLEDeviceManager, TuyaBLEDeviceCredentials

_LOGGER = logging.getLogger(__name__)

CONF_TUYA_DEVICE_KEYS = [
    CONF_UUID,
    CONF_LOCAL_KEY,
    CONF_DEVICE_ID,
    CONF_CATEGORY,
    CONF_PRODUCT_ID,
]


def has_local_credentials(data: dict[str, Any]) -> bool:
    """Check whether data holds everything needed to talk to the device."""
    return all(data.get(key) for key in CONF_TUYA_DEVICE_KEYS)


def credentials_from_data(data: dict[str, Any]) -> TuyaBLEDeviceCredentials | None:
    """Build device credentials from a config entry's stored data."""
    return AbstaractTuyaBLEDeviceManager.check_and_create_device_credentials(
        data.get(CONF_UUID),
        data.get(CONF_LOCAL_KEY),
        data.get(CONF_DEVICE_ID),
        data.get(CONF_CATEGORY),
        data.get(CONF_PRODUCT_ID),
        data.get(CONF_DEVICE_NAME),
        data.get(CONF_PRODUCT_MODEL),
        data.get(CONF_PRODUCT_NAME),
    )


class TuyaBLELocalDeviceManager(AbstaractTuyaBLEDeviceManager):
    """Manager of Tuya BLE device credentials entered by hand.

    The credentials are kept in the config entry, so the device is reached
    over Bluetooth only and neither a Tuya account nor a gateway is used.
    """

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        assert hass is not None
        self._hass = hass
        self._data = data

    async def build_cache(self) -> None:
        """Nothing to prefetch, the credentials are already local."""

    async def get_device_credentials(
        self,
        address: str,
        force_update: bool = False,
        save_data: bool = False,
    ) -> TuyaBLEDeviceCredentials | None:
        """Get credentials of the Tuya BLE device."""
        stored_address = self._data.get(CONF_ADDRESS)
        if stored_address and stored_address.upper() != address.upper():
            return None
        result = credentials_from_data(self._data)
        if result is None:
            _LOGGER.debug(
                "No local credentials stored for %s, device cannot be reached",
                address,
            )
            return None
        if save_data:
            self._data[CONF_AUTH_METHOD] = AUTH_METHOD_MANUAL
            self._data[CONF_ADDRESS] = address
        _LOGGER.debug("Retrieved locally: %s", result)
        return result

    @property
    def data(self) -> dict[str, Any]:
        return self._data
