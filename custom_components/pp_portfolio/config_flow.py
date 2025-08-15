
from __future__ import annotations
from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN, DEFAULT_PATH, CONF_PATH, CONF_INCLUDE_DETAILS

class PPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Portfolio Performance",
                data={CONF_PATH: user_input[CONF_PATH], CONF_INCLUDE_DETAILS: user_input.get(CONF_INCLUDE_DETAILS, True)},
            )

        schema = vol.Schema({
            vol.Required(CONF_PATH, default=DEFAULT_PATH): str,
            vol.Optional(CONF_INCLUDE_DETAILS, default=True): bool,
        })
        return self.async_show_form(step_id="user", data_schema=schema)
