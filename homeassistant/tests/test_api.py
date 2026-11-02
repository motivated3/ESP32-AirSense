"""Exercise real aiohttp requests and SQLite; only the HA view base is stubbed."""

import asyncio
from collections import deque
from datetime import UTC, datetime
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

PACKAGE = "air_monitor_under_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/air_monitor")]
sys.modules[PACKAGE] = package
http_stub = types.ModuleType("homeassistant.components.http")
http_stub.HomeAssistantView = type("HomeAssistantView", (), {})
sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
sys.modules.setdefault("homeassistant.components", types.ModuleType("homeassistant.components"))
sys.modules["homeassistant.components.http"] = http_stub
api = importlib.import_module(f"{PACKAGE}.api")
core = importlib.import_module(f"{PACKAGE}.core")


class Executor:
    config = types.SimpleNamespace(latitude=39.904, longitude=116.407)

    async def async_add_executor_job(self, function, *args):
        return await asyncio.to_thread(function, *args)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = core.UploadStore(Path(self.directory.name) / "archive.sqlite3")
        self.store.initialize()
        self.notifications = []
        self.runtime = types.SimpleNamespace(
            hass=Executor(), store=self.store, lock=asyncio.Lock(), stale_after=120,
            devices={"air_monitor_01": {"key_sha256": hashlib.sha256(b"test-key").hexdigest()}},
            current={}, minutes={}, last_contact={}, rate={}, notify=self.notifications.append,
        )
        app = web.Application()
        app.router.add_post("/ingest", api.IngestView(self.runtime).post)
        app.router.add_get("/minutes/{device_id}", api.MinuteHistoryView(self.runtime).get)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.headers = {"X-Air-Monitor-Device": "air_monitor_01", "Authorization": "Bearer test-key"}

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    def payload(self):
        return {"schema_version": 2, "device_id": "air_monitor_01", "session_id": "test-boot",
                "records": [{"seq": 1, "period_start": datetime.now(UTC).isoformat(), "sampled_at": datetime.now(UTC).isoformat(),
                             "uptime_ms": 5000, "clock_quality": "synced", "co2_ppm": None,
                             "hcho_ppb": None, "temperature_c": None, "humidity_pct": None}]}

    async def test_unauthorized_request_cannot_write(self):
        response = await self.client.post("/ingest", json=self.payload())
        self.assertEqual(response.status, 401)
        self.assertIsNone(self.store.latest("air_monitor_01"))

    async def test_acknowledged_retry_is_idempotent(self):
        data = self.payload()
        first = await self.client.post("/ingest", json=data, headers=self.headers)
        self.assertEqual(first.status, 200)
        self.assertEqual((await first.json())["inserted"], 1)
        retry = await self.client.post("/ingest", json=data, headers=self.headers)
        self.assertEqual((await retry.json())["duplicates"], 1)
        self.assertEqual(self.notifications, ["air_monitor_01", "air_monitor_01"])

    async def test_authenticated_ack_includes_ha_home_location(self):
        response = await self.client.post("/ingest", json=self.payload(), headers=self.headers)
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual(result["solar_location"], {"latitude": 39.904, "longitude": 116.407})
        self.assertEqual(result["accepted"], [1])

    async def test_invalid_home_location_never_breaks_ack(self):
        payload = self.payload()
        for latitude, longitude in ((91, 0), (0, -181), (float("nan"), 0), (True, 0)):
            self.runtime.hass.config = types.SimpleNamespace(latitude=latitude, longitude=longitude)
            response = await self.client.post("/ingest", json=payload, headers=self.headers)
            self.assertEqual(response.status, 200)
            self.assertNotIn("solar_location", await response.json())

    async def test_scope_is_enforced(self):
        data = self.payload()
        data["device_id"] = "another_device"
        response = await self.client.post("/ingest", json=data, headers=self.headers)
        self.assertEqual(response.status, 400)

    async def test_conflict_is_not_acknowledged(self):
        data = self.payload()
        await self.client.post("/ingest", json=data, headers=self.headers)
        data["records"][0]["co2_ppm"] = {"mean": 1000, "min": 1000, "max": 1000, "count": 1}
        response = await self.client.post("/ingest", json=data, headers=self.headers)
        self.assertEqual(response.status, 409)
        self.assertNotIn("accepted", await response.json())

    async def test_retry_recovers_runtime_after_commit_before_response_failure(self):
        data = self.payload()
        await self.client.post("/ingest", json=data, headers=self.headers)
        self.runtime.current.clear()  # A committed write can outlive a failed response/read.
        response = await self.client.post("/ingest", json=data, headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertIn("air_monitor_01", self.runtime.current)

    async def test_malformed_json_and_duplicate_keys_are_rejected(self):
        for text in ("{", '{"a":1,"a":2}', "[" * 2000):
            response = await self.client.post("/ingest", data=text,
                                              headers={**self.headers, "Content-Type": "application/json"})
            self.assertEqual(response.status, 400)

    async def test_chunked_body_limit_is_enforced(self):
        async def chunks():
            for _ in range(10):
                yield b" " * 8192
        response = await self.client.post("/ingest", data=chunks(),
                                          headers={**self.headers, "Content-Type": "application/json"})
        self.assertEqual(response.status, 413)

    async def test_wrong_content_type_is_rejected(self):
        response = await self.client.post("/ingest", data=json.dumps(self.payload()), headers=self.headers)
        self.assertEqual(response.status, 415)

    async def test_rate_limit_and_busy_writer_return_retryable_errors(self):
        self.runtime.rate["air_monitor_01"] = deque([time.monotonic()] * 60)
        response = await self.client.post("/ingest", json=self.payload(), headers=self.headers)
        self.assertEqual(response.status, 429)
        self.runtime.rate.clear()
        async with self.runtime.lock:
            response = await self.client.post("/ingest", json=self.payload(), headers=self.headers)
            self.assertEqual(response.status, 503)

    async def test_storage_failure_never_returns_ack(self):
        with sqlite3.connect(self.store.path) as db:
            db.execute("DROP TABLE minute_records")
        with self.assertLogs(api.__name__, level="ERROR"):
            response = await self.client.post("/ingest", json=self.payload(), headers=self.headers)
        self.assertEqual(response.status, 503)
        self.assertNotIn("accepted", await response.json())

    async def test_history_requires_ha_auth_and_limits_query_window(self):
        self.assertTrue(api.MinuteHistoryView.requires_auth)
        response = await self.client.get("/minutes/air_monitor_01?start=1&end=9999999999")
        self.assertEqual(response.status, 400)
        response = await self.client.get("/minutes/air_monitor_01?latest=1&authSig=ha-validated")
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual(result["points"], [])
        self.assertEqual(result["granularity_seconds"], 60)



if __name__ == "__main__":
    unittest.main()
