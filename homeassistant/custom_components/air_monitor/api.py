"""Bounded, device-scoped measurement uploads."""

import asyncio
from collections import deque
import json
import logging
import math
import re
import sqlite3
import time

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .core import ConflictError, ID_PATTERN, MAX_BODY, authenticate, validate_batch

_LOGGER = logging.getLogger(__name__)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _error(message, status, retry=False):
    return web.json_response({"error": message}, status=status,
                             headers={"Retry-After": "5"} if retry else None)


class IngestView(HomeAssistantView):
    url = "/api/air_monitor/ingest"
    name = "api:air_monitor:ingest"
    # This route authenticates its own device-only credential, never an HA token.
    requires_auth = False

    def __init__(self, runtime):
        self.runtime = runtime

    async def post(self, request):
        runtime = self.runtime
        device_id = request.headers.get("X-Air-Monitor-Device", "")
        if not authenticate(runtime.devices, device_id, request.headers.get("Authorization")):
            return _error("invalid device credential", 401)
        recent = runtime.rate.setdefault(device_id, deque())
        now_mono = time.monotonic()
        while recent and recent[0] <= now_mono - 60:
            recent.popleft()
        if len(recent) >= 60:
            return _error("rate limit exceeded", 429, True)
        recent.append(now_mono)
        if request.content_type != "application/json":
            return _error("Content-Type must be application/json", 415)
        if request.content_length is not None and request.content_length > MAX_BODY:
            return _error("body exceeds 64 KiB", 413)
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.content.iter_chunked(8192):
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        return _error("body exceeds 64 KiB", 413)
            data = json.loads(body, object_pairs_hook=_unique_object)
            batch = validate_batch(data, device_id, time.time())
        except TimeoutError:
            return _error("upload timed out", 408, True)
        except (ValueError, UnicodeError, RecursionError):
            return _error("invalid version 2 minute batch", 400)
        if runtime.lock.locked():
            return _error("upload writer busy", 503, True)
        async with runtime.lock:
            now = time.time()
            try:
                result = await runtime.hass.async_add_executor_job(
                    runtime.store.save, batch, now, runtime.stale_after
                )
                # Also recover a previously committed write whose response/read failed.
                runtime.current[device_id] = await runtime.hass.async_add_executor_job(
                    runtime.store.latest, device_id
                )
            except ConflictError:
                return _error("sequence conflict; entire batch rolled back", 409)
            except (sqlite3.Error, OSError):
                _LOGGER.exception("Air monitor upload storage operation failed")
                return _error("upload storage unavailable; retry the identical batch", 503, True)
            runtime.last_contact[device_id] = now
            runtime.notify(device_id)
        response = {"schema_version": 2, "device_id": device_id,
                    "session_id": batch.session_id, **result}
        latitude, longitude = runtime.hass.config.latitude, runtime.hass.config.longitude
        if (type(latitude) in (int, float) and type(longitude) in (int, float)
                and math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            response["solar_location"] = {"latitude": latitude, "longitude": longitude}
        return web.json_response(response)



class MinuteHistoryView(HomeAssistantView):
    """Minute chart data inside HA, protected by HA login, never device keys."""

    url = "/api/air_monitor/minutes/{device_id}"
    name = "api:air_monitor:minutes"
    requires_auth = True

    def __init__(self, runtime):
        self.runtime = runtime

    async def get(self, request, device_id=None):
        device_id = device_id or request.match_info["device_id"]
        if not re.fullmatch(ID_PATTERN, device_id) or device_id not in self.runtime.devices:
            return _error("unknown device", 404)
        try:
            if set(request.query) - {"start", "end", "latest", "authSig"}:
                raise ValueError("unknown query parameter")
            latest = request.query.get("latest")
            if latest is not None:
                if latest != "1" or "start" in request.query or "end" in request.query:
                    raise ValueError("latest=1 cannot be combined with a time range")
                points = await self.runtime.hass.async_add_executor_job(self.runtime.store.latest_trip, device_id)
            else:
                now = int(time.time())
                start_raw, end_raw = request.query.get("start", str(now-86400)), request.query.get("end", str(now))
                if not re.fullmatch(r"[0-9]{1,11}", start_raw) or not re.fullmatch(r"[0-9]{1,11}", end_raw):
                    raise ValueError("invalid timestamps")
                start, end = int(start_raw), int(end_raw)
                if not 0 <= start < end or end-start > 31*86400:
                    raise ValueError("choose a time range of at most 31 days")
                points = await self.runtime.hass.async_add_executor_job(self.runtime.store.history, device_id, start, end)
        except ValueError as err:
            return _error(str(err), 400)
        except (sqlite3.Error, OSError):
            _LOGGER.exception("Air monitor minute history read failed")
            return _error("minute history unavailable", 503, True)
        compact = [{"t": p["sampled_epoch"], "start": p["period_start_epoch"],
                    **{field: p[field] for field in ("co2_ppm", "hcho_ppb", "temperature_c", "humidity_pct")}}
                   for p in points]
        return web.json_response({"device_id": device_id, "granularity_seconds": 60,
                                  "retention": "permanent", "points": compact},
                                 headers={"Cache-Control": "no-store"})
