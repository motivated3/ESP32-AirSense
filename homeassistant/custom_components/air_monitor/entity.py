"""Shared push updates for YAML air-monitor entities."""

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from . import SIGNAL


class AirMonitorEntity(Entity):
    _attr_should_poll = False

    def __init__(self, runtime, device_id):
        self.runtime = runtime
        self.device_id = device_id

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL.format(self.device_id), self._update
        ))

    @callback
    def _update(self):
        self.async_write_ha_state()
