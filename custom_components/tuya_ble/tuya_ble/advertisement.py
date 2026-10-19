"""Decoding of the data broadcasted by Tuya BLE devices.

Tuya BLE devices advertise their product id in plain text and their uuid
encrypted with a key derived from that product id. Both are therefore
available without any cloud access, which allows prefilling most of the
device credentials during setup.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from Crypto.Cipher import AES

from .const import MANUFACTURER_DATA_ID, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)

SERVICE_DATA_TYPE_PRODUCT_ID = 0
UUID_LENGTH = 16


@dataclass
class TuyaBLEAdvertisement:
    """Data decoded from an advertisement of a Tuya BLE device."""

    product_id: str | None = None
    uuid: str | None = None
    is_bound: bool = False
    protocol_version: int = 2
    # False when the device state was not part of the advertisement, in which
    # case is_bound and protocol_version are only defaults.
    has_device_state: bool = False


def _decrypt_uuid(raw_product_id: bytes, raw_uuid: bytes) -> str | None:
    """Decrypt the uuid broadcasted in the manufacturer specific data."""
    if len(raw_uuid) < UUID_LENGTH:
        return None
    key = hashlib.md5(raw_product_id).digest()
    cipher = AES.new(key, AES.MODE_CBC, key)
    try:
        return cipher.decrypt(raw_uuid[:UUID_LENGTH]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as ex:
        _LOGGER.debug("Could not decode advertised uuid: %s", ex)
        return None


def parse_advertisement(
    service_data: dict[str, bytes] | None,
    manufacturer_data: dict[int, bytes] | None,
) -> TuyaBLEAdvertisement:
    """Decode the advertisement data of a Tuya BLE device."""
    result = TuyaBLEAdvertisement()
    raw_product_id: bytes | None = None

    if service_data:
        data = service_data.get(SERVICE_UUID)
        if data and len(data) > 1 and data[0] == SERVICE_DATA_TYPE_PRODUCT_ID:
            raw_product_id = data[1:]
            try:
                result.product_id = raw_product_id.decode("utf-8")
            except UnicodeDecodeError:
                _LOGGER.debug("Could not decode advertised product id")

    if manufacturer_data:
        data = manufacturer_data.get(MANUFACTURER_DATA_ID)
        if data and len(data) > 6:
            result.has_device_state = True
            result.is_bound = (data[0] & 0x80) != 0
            result.protocol_version = data[1]
            if raw_product_id:
                result.uuid = _decrypt_uuid(raw_product_id, data[6:])

    return result
