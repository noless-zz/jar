"""Set up Jar by pasting the link from the Jar dashboard (Home Assistant page)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JarApi, JarAuthError, JarError, JarUnreachable, parse_link
from .const import CONF_CONTROL, CONF_TOKEN, CONF_URLS, DOMAIN

LINK = "link"


async def _check(hass, link: str) -> tuple[dict, dict[str, str]]:
    """(entry data, errors)."""
    try:
        token, urls = parse_link(link)
    except ValueError:
        return {}, {LINK: "bad_link"}
    api = JarApi(async_get_clientsession(hass), token, urls)
    try:
        who = await api.auth()
    except JarAuthError:
        return {}, {LINK: "bad_token"}
    except JarUnreachable:
        return {}, {"base": "cannot_connect"}
    except JarError:
        return {}, {"base": "unknown"}
    if (who.get("person") or {}).get("role") != "home":
        return {}, {LINK: "not_home_link"}
    return {CONF_TOKEN: token, CONF_URLS: api.urls[api._good:] + api.urls[:api._good]}, {}


class JarConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await _check(self.hass, user_input[LINK])
            if not errors:
                return self.async_create_entry(title="Jar", data={**data, CONF_CONTROL: user_input[CONF_CONTROL]})
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required(LINK): str,
            vol.Required(CONF_CONTROL, default=True): bool,
        }))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await _check(self.hass, user_input[LINK])
            if not errors:
                return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=data)
        return self.async_show_form(step_id="reconfigure", errors=errors,
                                    data_schema=vol.Schema({vol.Required(LINK): str}))

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await _check(self.hass, user_input[LINK])
            if not errors:
                return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        return self.async_show_form(step_id="reauth_confirm", errors=errors,
                                    data_schema=vol.Schema({vol.Required(LINK): str}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return JarOptionsFlow()


class JarOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_CONTROL, self.config_entry.data.get(CONF_CONTROL, True))
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_CONTROL, default=current): bool}))
