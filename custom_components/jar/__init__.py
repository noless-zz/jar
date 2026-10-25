"""Jar: the family's voice-memo task list on Home Assistant.

A to-do list per family member (tick a task on the wall panel and it counts for that person), coins sensors,
the jar.add_task action and jar_task_done / jar_task_new events. With "Let Jar control the house" on, it also
makes a Home Assistant user "Jar" with a token and hands both to Jar, so memos can switch things via Assist.
"""

from __future__ import annotations

import inspect
import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.typing import ConfigType

from .api import JarApi, JarError
from .const import CONF_CONTROL, CONF_HA_USER, CONF_TOKEN, CONF_URLS, DOMAIN, HA_USER_NAME
from .coordinator import JarCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type JarConfigEntry = ConfigEntry[JarCoordinator]

ADD_TASK_SCHEMA = vol.Schema({
    vol.Required("title"): cv.string,
    vol.Required("people"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("due"): cv.string,
    vol.Optional("notes", default=""): cv.string,
    vol.Optional("each_of_them", default=False): cv.boolean,
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def add_task(call: ServiceCall) -> dict:
        entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN)]
        if not entries:
            raise ServiceValidationError("Jar isn't set up")
        coord: JarCoordinator = entries[0].runtime_data
        fam = coord.data.family if coord.data else []
        ids = []
        for who in call.data["people"]:
            w = who.strip().casefold()
            p = next((p for p in fam if w in (p["id"].casefold(), p["name"].casefold())), None)
            if p is None:
                raise ServiceValidationError(f"no family member '{who}' in Jar")
            ids.append(p["id"])
        try:
            t = await coord.api.add_task(call.data["title"], ids, call.data.get("due"), call.data["notes"],
                                         "all" if call.data["each_of_them"] else "any")
        except JarError as e:
            raise HomeAssistantError(f"Jar: {e}") from e
        await coord.async_request_refresh()
        return {"id": t.get("id"), "title": t.get("title")}

    hass.services.async_register(DOMAIN, "add_task", add_task, schema=ADD_TASK_SCHEMA,
                                 supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: JarConfigEntry) -> bool:
    api = JarApi(async_get_clientsession(hass), entry.data[CONF_TOKEN], entry.data[CONF_URLS])
    coord = JarCoordinator(hass, entry, api)
    await coord.async_config_entry_first_refresh()
    entry.runtime_data = coord
    coord.control = _control_on(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    try:
        await _sync_control(hass, entry, api)
    except (JarError, NoURLAvailableError) as e:
        _LOGGER.warning("Couldn't give Jar control of the house yet: %s", e)
    return True


def _control_on(entry: ConfigEntry) -> bool:
    return bool(entry.options.get(CONF_CONTROL, entry.data.get(CONF_CONTROL, True)))


async def _options_changed(hass: HomeAssistant, entry: JarConfigEntry) -> None:
    if _control_on(entry) != getattr(entry.runtime_data, "control", None):   # not for our own data updates
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: JarConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Removing the integration takes Jar's access to the house away too."""
    api = JarApi(async_get_clientsession(hass), entry.data[CONF_TOKEN], entry.data[CONF_URLS])
    try:
        await api.link_home("", "")
    except JarError as e:
        _LOGGER.warning("Couldn't tell Jar to forget Home Assistant: %s", e)
    await _remove_user(hass, entry.data.get(CONF_HA_USER))


async def _sync_control(hass: HomeAssistant, entry: ConfigEntry, api: JarApi) -> None:
    """Allowed: a Home Assistant user "Jar" (not an admin) + a token for it, given to Jar. Not allowed: none."""
    from homeassistant.auth.const import GROUP_ID_USER
    from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN

    uid = entry.data.get(CONF_HA_USER)
    if not _control_on(entry):
        if uid:
            await api.link_home("", "")
            await _remove_user(hass, uid)
            hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HA_USER: None})
        return
    user = await hass.auth.async_get_user(uid) if uid else None
    status = await api._request("GET", "/v1/home")
    if user is not None and status.get("linked"):
        return                                                    # already done
    url = get_url(hass, prefer_external=True, allow_internal=True, allow_ip=True)
    if user is None:
        user = await hass.auth.async_create_user(HA_USER_NAME, group_ids=[GROUP_ID_USER])
        if user.is_owner:            # no one had an account yet: Jar mustn't become the owner
            await hass.auth.async_remove_user(user)
            _LOGGER.warning("Create your own Home Assistant account first, then reload Jar")
            return
    for rt in list(user.refresh_tokens.values()):
        if rt.client_name == HA_USER_NAME:
            await _maybe_await(hass.auth.async_remove_refresh_token(rt))
    rt = await hass.auth.async_create_refresh_token(
        user, client_name=HA_USER_NAME, token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
        access_token_expiration=timedelta(days=3650))
    await api.link_home(url, hass.auth.async_create_access_token(rt))
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HA_USER: user.id})
    _LOGGER.info("Jar can now control the house through %s", url)


async def _remove_user(hass: HomeAssistant, uid: str | None) -> None:
    if not uid:
        return
    user = await hass.auth.async_get_user(uid)
    if user is not None and user.name == HA_USER_NAME and not user.is_owner:
        await hass.auth.async_remove_user(user)


async def _maybe_await(x) -> None:
    if inspect.isawaitable(x):
        await x
