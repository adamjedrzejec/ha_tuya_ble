"""Config flow for Tuya BLE integration."""

from __future__ import annotations

import logging
from collections import namedtuple
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
)
from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_ID
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowHandler, FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

Country = namedtuple("Country", ["name", "country_code", "endpoint"])

CONF_ACCESS_ID = "access_id"
CONF_ACCESS_SECRET = "access_secret"
CONF_APP_TYPE = "app_type"
CONF_AUTH_TYPE = "auth_type"
CONF_COUNTRY_CODE = "country_code"
CONF_ENDPOINT = "endpoint"
CONF_PASSWORD = "password"
CONF_USERNAME = "username"
SMARTLIFE_APP = "smartlife"
TUYA_SMART_APP = "tuyaSmart"
TUYA_RESPONSE_CODE = "code"
TUYA_RESPONSE_MSG = "msg"
TUYA_RESPONSE_SUCCESS = "success"

TUYA_COUNTRIES = [
    Country("Poland", "48", "https://openapi.tuyaeu.com"),
    Country("Europe", "49", "https://openapi.tuyaeu.com"),
    Country("United States", "1", "https://openapi.tuyaus.com"),
    Country("United Kingdom", "44", "https://openapi.tuyaeu.com"),
    Country("China", "86", "https://openapi.tuyacn.com"),
]

from .cloud import TUYA_IOT_AVAILABLE, HASSTuyaBLEDeviceManager
from .const import (
    AUTH_METHOD_CLOUD,
    AUTH_METHOD_MANUAL,
    CONF_AUTH_METHOD,
    CONF_CATEGORY,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_UUID,
    DEVICE_ID_LENGTH,
    DOMAIN,
    LOCAL_KEY_MIN_LENGTH,
    UUID_LENGTH,
)
from .devices import (
    categories_database,
    get_category_by_product_id,
    get_device_readable_name,
)
from .local import TuyaBLELocalDeviceManager, has_local_credentials
from .tuya_ble import (
    SERVICE_UUID,
    AbstaractTuyaBLEDeviceManager,
    TuyaBLEDeviceCredentials,
    parse_advertisement,
)

_LOGGER = logging.getLogger(__name__)


async def _try_login(
    manager: HASSTuyaBLEDeviceManager,
    user_input: dict[str, Any],
    errors: dict[str, str],
    placeholders: dict[str, Any],
) -> dict[str, Any] | None:
    response: dict[Any, Any] | None = None
    data: dict[str, Any]

    if not TUYA_IOT_AVAILABLE:
        errors["base"] = "cloud_unavailable"
        return None

    from tuya_iot import AuthType

    country = [
        country
        for country in TUYA_COUNTRIES
        if country.name == user_input[CONF_COUNTRY_CODE]
    ][0]

    data = {
        CONF_ENDPOINT: country.endpoint,
        CONF_AUTH_TYPE: AuthType.CUSTOM,
        CONF_ACCESS_ID: user_input[CONF_ACCESS_ID],
        CONF_ACCESS_SECRET: user_input[CONF_ACCESS_SECRET],
        CONF_USERNAME: user_input[CONF_USERNAME],
        CONF_PASSWORD: user_input[CONF_PASSWORD],
        CONF_COUNTRY_CODE: country.country_code,
    }

    for app_type in (TUYA_SMART_APP, SMARTLIFE_APP, ""):
        data[CONF_APP_TYPE] = app_type
        if app_type == "":
            data[CONF_AUTH_TYPE] = AuthType.CUSTOM
        else:
            data[CONF_AUTH_TYPE] = AuthType.SMART_HOME

        response = await manager._login(data, True)

        if response.get(TUYA_RESPONSE_SUCCESS, False):
            data[CONF_AUTH_METHOD] = AUTH_METHOD_CLOUD
            return data

    errors["base"] = "login_error"
    if response:
        placeholders.update(
            {
                TUYA_RESPONSE_CODE: response.get(TUYA_RESPONSE_CODE),
                TUYA_RESPONSE_MSG: response.get(TUYA_RESPONSE_MSG),
            }
        )

    return None


def _show_login_form(
    flow: FlowHandler,
    user_input: dict[str, Any],
    errors: dict[str, str],
    placeholders: dict[str, Any],
) -> FlowResult:
    """Shows the Tuya IOT platform login form."""
    if user_input is not None and user_input.get(CONF_COUNTRY_CODE) is not None:
        for country in TUYA_COUNTRIES:
            if country.country_code == user_input[CONF_COUNTRY_CODE]:
                user_input[CONF_COUNTRY_CODE] = country.name
                break

    def_country_name: str | None = None
    try:
        import pycountry

        def_country = pycountry.countries.get(alpha_2=flow.hass.config.country)
        if def_country:
            def_country_name = def_country.name
    except Exception:  # noqa: BLE001 - only used to preselect a country
        pass

    return flow.async_show_form(
        step_id="login",
        data_schema=vol.Schema(
            {
                vol.Required(
                    CONF_COUNTRY_CODE,
                    default=user_input.get(CONF_COUNTRY_CODE, def_country_name),
                ): vol.In(
                    # We don't pass a dict {code:name} because country codes can be duplicate.
                    [country.name for country in TUYA_COUNTRIES]
                ),
                vol.Required(
                    CONF_ACCESS_ID, default=user_input.get(CONF_ACCESS_ID, "")
                ): str,
                vol.Required(
                    CONF_ACCESS_SECRET,
                    default=user_input.get(CONF_ACCESS_SECRET, ""),
                ): str,
                vol.Required(
                    CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                ): str,
            }
        ),
        errors=errors,
        description_placeholders=placeholders,
    )


def _category_selector() -> SelectSelector:
    """Selector of the device category, which also accepts an unlisted one."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=category, label=f"{name} ({category})")
                for category, name in sorted(
                    categories_database.items(), key=lambda item: item[1]
                )
            ],
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _validate_credentials(
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> dict[str, Any] | None:
    """Validate manually entered device credentials."""
    data = {key: str(value).strip() for key, value in user_input.items()}

    if len(data.get(CONF_UUID, "")) != UUID_LENGTH:
        errors[CONF_UUID] = "invalid_uuid"
    if len(data.get(CONF_DEVICE_ID, "")) != DEVICE_ID_LENGTH:
        errors[CONF_DEVICE_ID] = "invalid_device_id"
    if len(data.get(CONF_LOCAL_KEY, "")) < LOCAL_KEY_MIN_LENGTH:
        errors[CONF_LOCAL_KEY] = "invalid_local_key"
    if not data.get(CONF_CATEGORY):
        errors[CONF_CATEGORY] = "invalid_category"
    if not data.get(CONF_PRODUCT_ID):
        errors[CONF_PRODUCT_ID] = "invalid_product_id"

    if errors:
        return None

    data[CONF_AUTH_METHOD] = AUTH_METHOD_MANUAL
    if not data.get(CONF_DEVICE_NAME):
        data.pop(CONF_DEVICE_NAME, None)
    return data


def _suggest(key: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """Prefill a field only when a value for it is known."""
    value = user_input.get(key)
    return {"description": {"suggested_value": value}} if value else {}


def _show_credentials_form(
    flow: FlowHandler,
    user_input: dict[str, Any],
    errors: dict[str, str],
    placeholders: dict[str, Any],
) -> FlowResult:
    """Shows the form for entering the device credentials by hand."""
    return flow.async_show_form(
        step_id="credentials",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_UUID, **_suggest(CONF_UUID, user_input)): str,
                vol.Required(
                    CONF_DEVICE_ID, **_suggest(CONF_DEVICE_ID, user_input)
                ): str,
                vol.Required(
                    CONF_LOCAL_KEY, **_suggest(CONF_LOCAL_KEY, user_input)
                ): str,
                vol.Required(
                    CONF_CATEGORY, **_suggest(CONF_CATEGORY, user_input)
                ): _category_selector(),
                vol.Required(
                    CONF_PRODUCT_ID, **_suggest(CONF_PRODUCT_ID, user_input)
                ): str,
                vol.Optional(
                    CONF_DEVICE_NAME, **_suggest(CONF_DEVICE_NAME, user_input)
                ): str,
            }
        ),
        errors=errors,
        description_placeholders=placeholders,
    )


def _credentials_from_advertisement(
    discovery_info: BluetoothServiceInfoBleak | None,
) -> dict[str, Any]:
    """Prefill what the device broadcasts itself: its uuid and product id."""
    result: dict[str, Any] = {}
    if discovery_info is None:
        return result
    advertisement = parse_advertisement(
        discovery_info.service_data,
        discovery_info.manufacturer_data,
    )
    if advertisement.uuid:
        result[CONF_UUID] = advertisement.uuid
    if advertisement.product_id:
        result[CONF_PRODUCT_ID] = advertisement.product_id
        category = get_category_by_product_id(advertisement.product_id)
        if category:
            result[CONF_CATEGORY] = category
    return result


class TuyaBLEOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle a Tuya BLE options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)
        self._data: dict[str, Any] = dict(config_entry.options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose how the credentials are provided."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["credentials", "login"],
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle editing the device credentials by hand."""
        errors: dict[str, str] = {}
        placeholders: dict[str, Any] = {
            CONF_ADDRESS: self.config_entry.data.get(CONF_ADDRESS, "")
        }

        if user_input is not None:
            data = _validate_credentials(user_input, errors)
            if data:
                self._data.update(data)
                return self.async_create_entry(
                    title=self.config_entry.title,
                    data=self._data,
                )
        else:
            user_input = {
                key: self._data.get(key, "")
                for key in (
                    CONF_UUID,
                    CONF_DEVICE_ID,
                    CONF_LOCAL_KEY,
                    CONF_CATEGORY,
                    CONF_PRODUCT_ID,
                    CONF_DEVICE_NAME,
                )
            }

        return _show_credentials_form(self, user_input, errors, placeholders)

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the optional Tuya IOT platform login step."""
        errors: dict[str, str] = {}
        placeholders: dict[str, Any] = {}
        credentials: TuyaBLEDeviceCredentials | None = None
        address: str | None = self.config_entry.data.get(CONF_ADDRESS)

        if user_input is not None:
            manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
            login_data = await _try_login(
                manager,
                user_input,
                errors,
                placeholders,
            )
            if login_data:
                self._data.update(login_data)
                credentials = await manager.get_device_credentials(
                    address, True, True
                )
                if credentials:
                    return self.async_create_entry(
                        title=self.config_entry.title,
                        data=manager.data,
                    )
                errors["base"] = "device_not_registered"

        if user_input is None:
            user_input = dict(self._data)

        return _show_login_form(self, user_input, errors, placeholders)


class TuyaBLEConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._data: dict[str, Any] = {}
        self._manager: HASSTuyaBLEDeviceManager | None = None
        self._get_device_info_error = False

    @property
    def _cloud_manager(self) -> HASSTuyaBLEDeviceManager:
        """Manager used to look credentials up in the cloud, if asked for."""
        if self._manager is None:
            self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
        return self._manager

    async def _async_build_cache(self) -> None:
        """Pick up credentials of the official Tuya integration, if present."""
        try:
            await self._cloud_manager.build_cache()
        except Exception as ex:  # noqa: BLE001 - the cloud is entirely optional
            _LOGGER.debug("Could not read credentials from Tuya cloud: %s", ex)

    async def _async_readable_name(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> str:
        return await get_device_readable_name(discovery_info, self._cloud_manager)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        await self._async_build_cache()
        self.context["title_placeholders"] = {
            "name": await self._async_readable_name(discovery_info)
        }
        self._data[CONF_ADDRESS] = discovery_info.address
        return await self.async_step_setup_method()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step."""
        await self._async_build_cache()
        return await self.async_step_device()

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            self._discovery_info = self._discovered_devices[address]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._data[CONF_ADDRESS] = address
            return await self.async_step_setup_method()

        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids()
            for discovery in async_discovered_service_info(self.hass):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                    or discovery.service_data is None
                    or not SERVICE_UUID in discovery.service_data.keys()
                ):
                    continue
                self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_unconfigured_devices")

        def_address: str
        if user_input:
            def_address = user_input.get(CONF_ADDRESS)
        else:
            def_address = list(self._discovered_devices)[0]

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADDRESS,
                        default=def_address,
                    ): vol.In(
                        {
                            service_info.address: await self._async_readable_name(
                                service_info
                            )
                            for service_info in self._discovered_devices.values()
                        }
                    ),
                },
            ),
            errors=errors,
        )

    async def async_step_setup_method(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose between local credentials and a cloud lookup."""
        return self.async_show_menu(
            step_id="setup_method",
            menu_options=["credentials", "login"],
        )

    async def _async_create_entry(
        self, manager: AbstaractTuyaBLEDeviceManager
    ) -> FlowResult:
        address: str = self._data[CONF_ADDRESS]
        if self._discovery_info:
            title = await get_device_readable_name(self._discovery_info, manager)
        else:
            title = address
        return self.async_create_entry(
            title=title,
            data={CONF_ADDRESS: address},
            options=self._data,
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle entering the device credentials by hand, without the cloud."""
        errors: dict[str, str] = {}
        placeholders: dict[str, Any] = {
            CONF_ADDRESS: self._data.get(CONF_ADDRESS, "")
        }

        if user_input is not None:
            data = _validate_credentials(user_input, errors)
            if data:
                self._data.update(data)
                return await self._async_create_entry(
                    TuyaBLELocalDeviceManager(self.hass, self._data)
                )
        else:
            user_input = _credentials_from_advertisement(self._discovery_info)

        return _show_credentials_form(self, user_input, errors, placeholders)

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the optional Tuya IOT platform login step."""
        data: dict[str, Any] | None = None
        errors: dict[str, str] = {}
        placeholders: dict[str, Any] = {}
        address: str = self._data[CONF_ADDRESS]

        if user_input is not None:
            data = await _try_login(
                self._cloud_manager,
                user_input,
                errors,
                placeholders,
            )
            if data:
                self._data.update(data)
                credentials = await self._cloud_manager.get_device_credentials(
                    address, self._get_device_info_error, True
                )
                if credentials:
                    return await self._async_create_entry(self._cloud_manager)
                self._get_device_info_error = True
                errors["base"] = "device_not_registered"

        if user_input is None:
            # Credentials may already be known from the official Tuya
            # integration, in which case no login is needed at all.
            await self._cloud_manager.get_device_credentials(address, False, True)
            if has_local_credentials(self._data):
                return await self._async_create_entry(self._cloud_manager)
            self._cloud_manager.get_login_from_cache()
            user_input = dict(self._data)

        return _show_login_form(self, user_input, errors, placeholders)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> TuyaBLEOptionsFlow:
        """Get the options flow for this handler."""
        return TuyaBLEOptionsFlow(config_entry)
