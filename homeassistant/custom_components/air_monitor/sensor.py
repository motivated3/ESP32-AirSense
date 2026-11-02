"""Current measurements; old/unsynced receipts never become live data."""

import time

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfRatio, UnitOfTemperature

from . import DOMAIN
from .core import is_fresh
from .entity import AirMonitorEntity

METRICS = (
    ("co2", "co2_ppm", "CO₂", UnitOfRatio.PARTS_PER_MILLION, SensorDeviceClass.CO2),
    ("hcho", "hcho_ppb", "甲醛", "ppb", None),
    ("temperature", "temperature_c", "温度", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    ("humidity", "humidity_pct", "湿度", PERCENTAGE, SensorDeviceClass.HUMIDITY),
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    runtime = hass.data[DOMAIN]
    async_add_entities([AirMonitorSensor(runtime, device, metric)
                        for device in runtime.devices for metric in METRICS])


class AirMonitorSensor(AirMonitorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, runtime, device_id, metric):
        super().__init__(runtime, device_id)
        slug, self.field, name, unit, device_class = metric
        self.entity_id = f"sensor.{device_id.lower()}_{slug}"
        self._attr_unique_id = f"{device_id}_{slug}"
        self._attr_name = f'{runtime.devices[device_id]["name"]} {name}'
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    @property
    def available(self):
        record = self.runtime.current.get(self.device_id)
        return is_fresh(record, time.time(), self.runtime.stale_after) and record[self.field] is not None

    @property
    def native_value(self):
        record = self.runtime.current.get(self.device_id)
        return record[self.field]["mean"] if record and record[self.field] is not None else None

    @property
    def extra_state_attributes(self):
        record = self.runtime.current.get(self.device_id)
        if record is None:
            return {"device_id": self.device_id}
        return {"device_id": self.device_id, "sampled_at": record["sampled_at"],
                "session_id": record["session_id"], "seq": record["seq"],
                "clock_quality": record["clock_quality"], "period_start": record["period_start"],
                "minimum": record[self.field]["min"] if record[self.field] else None,
                "maximum": record[self.field]["max"] if record[self.field] else None,
                "sample_count": record[self.field]["count"] if record[self.field] else 0}
