"""Connectivity is independent of measurement validity and freshness."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from . import DOMAIN
from .entity import AirMonitorEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    runtime = hass.data[DOMAIN]
    async_add_entities([AirMonitorOnline(runtime, device) for device in runtime.devices])


class AirMonitorOnline(AirMonitorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, runtime, device_id):
        super().__init__(runtime, device_id)
        self.entity_id = f"binary_sensor.{device_id.lower()}_online"
        self._attr_unique_id = f"{device_id}_online"
        self._attr_name = f'{runtime.devices[device_id]["name"]} 在线'

    @property
    def is_on(self):
        return self.runtime.online(self.device_id)
