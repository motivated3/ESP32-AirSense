"""Device-scoped air monitor ingestion, configured through YAML."""

import asyncio
from datetime import timedelta
import time

import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .api import IngestView, MinuteHistoryView
from .core import UploadStore, ID_PATTERN

DOMAIN = "air_monitor"
SIGNAL = "air_monitor_update_{}"
DEVICE_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Required("key_sha256"): vol.All(cv.string, vol.Match(r"^[0-9a-f]{64}$")),
})
CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required("devices"): vol.All(
            {vol.Match(f"^{ID_PATTERN}$"): DEVICE_SCHEMA}, vol.Length(min=1, max=100)
        ),
        vol.Optional("stale_after", default=120): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
    }),
}, extra=vol.ALLOW_EXTRA)


class Runtime:
    def __init__(self, hass, settings):
        self.hass = hass
        self.devices = settings["devices"]
        self.stale_after = settings["stale_after"]
        self.store = UploadStore(hass.config.path(".storage", "air_monitor.sqlite3"))
        self.lock = asyncio.Lock()
        self.current = {}
        self.last_contact = {}
        self.rate = {}

    @callback
    def notify(self, device_id):
        async_dispatcher_send(self.hass, SIGNAL.format(device_id))

    @callback
    def tick(self, _now):
        for device_id in self.devices:
            self.notify(device_id)

    def online(self, device_id):
        contact = self.last_contact.get(device_id)
        return contact is not None and 0 <= time.time() - contact <= self.stale_after

    def initialize(self):
        self.store.initialize()
        self.current = {device: self.store.latest(device) for device in self.devices}



async def async_setup(hass, config):
    if DOMAIN not in config:
        return True
    runtime = Runtime(hass, config[DOMAIN])
    await hass.async_add_executor_job(runtime.initialize)
    hass.data[DOMAIN] = runtime
    hass.http.register_view(IngestView(runtime))
    hass.http.register_view(MinuteHistoryView(runtime))
    cancel = async_track_time_interval(hass, runtime.tick, timedelta(seconds=15))

    @callback
    def stop(_event):
        cancel()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    for platform in ("sensor", "binary_sensor"):
        hass.async_create_task(
            discovery.async_load_platform(hass, platform, DOMAIN, {}, config)
        )
    return True
