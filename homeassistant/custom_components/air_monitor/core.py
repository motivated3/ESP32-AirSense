"""Versioned air-monitor protocol and permanent one-minute statistics.

This module uses only the standard library. Call storage methods in an executor.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3

ID_PATTERN = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}"
MAX_BODY = 65536
MAX_RECORDS = 100
MAX_INTEGER = 2**63 - 1
METRICS = {
    "co2_ppm": (400, 5000),
    "hcho_ppb": (0, 1000),
    "temperature_c": (-10, 60),
    "humidity_pct": (0, 95),
}
RECORD_FIELDS = {"seq", "period_start", "sampled_at", "uptime_ms", "clock_quality", *METRICS}


@dataclass(frozen=True)
class Batch:
    device_id: str
    session_id: str
    records: tuple[dict, ...]


class ConflictError(ValueError):
    """A sequence was retried with different contents."""


def authenticate(devices: dict, device_id: str, authorization: str | None) -> bool:
    """Device credentials grant upload access only to that configured device."""
    device = devices.get(device_id)
    if not device or not isinstance(authorization, str):
        return False
    if not authorization.startswith("Bearer ") or len(authorization) > 1024:
        return False
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    return hmac.compare_digest(digest, device["key_sha256"])


def _integer(value) -> bool:
    return type(value) is int and 0 <= value <= MAX_INTEGER


def validate_batch(data, device_id: str, now: float) -> Batch:
    """Validate the entire batch before any database write; normalize UTC."""
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "device_id", "session_id", "records"
    }:
        raise ValueError("invalid envelope fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 2:
        raise ValueError("schema_version must be 2")
    if data["device_id"] != device_id:
        raise ValueError("device_id does not match credential")
    for field in ("device_id", "session_id"):
        if not isinstance(data[field], str) or not re.fullmatch(ID_PATTERN, data[field]):
            raise ValueError(f"invalid {field}")
    records = data["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError("records must contain 1..100 entries")
    normalized, sequences = [], set()
    for raw in records:
        if not isinstance(raw, dict) or set(raw) != RECORD_FIELDS:
            raise ValueError("invalid record fields; units are fixed by field names")
        record = raw.copy()
        if not _integer(record["seq"]) or record["seq"] in sequences:
            raise ValueError("seq must be a unique nonnegative int64")
        sequences.add(record["seq"])
        if not _integer(record["uptime_ms"]):
            raise ValueError("uptime_ms must be a nonnegative int64")
        quality, sampled = record["clock_quality"], record["sampled_at"]
        period_start = record["period_start"]
        if quality == "unsynced" and sampled is None and period_start is None:
            record["sampled_epoch"] = None
            record["period_start_epoch"] = None
        elif quality == "synced" and isinstance(sampled, str) and len(sampled) <= 40:
            try:
                dt = datetime.fromisoformat(sampled)
                if dt.tzinfo is None:
                    raise ValueError("timezone is required")
                epoch = dt.timestamp()
                if not 1577836800 <= epoch <= now + 30:
                    raise ValueError("sample time outside allowed range")
                record["sampled_at"] = dt.astimezone(UTC).isoformat()
                record["sampled_epoch"] = epoch
                if not isinstance(period_start, str) or len(period_start) > 40:
                    raise ValueError("period_start is required")
                start_dt = datetime.fromisoformat(period_start)
                if start_dt.tzinfo is None:
                    raise ValueError("timezone is required")
                start_epoch = start_dt.timestamp()
                if not 1577836800 <= start_epoch <= epoch or epoch - start_epoch > 60:
                    raise ValueError("measurement interval must be 0..60 seconds")
                record["period_start"] = start_dt.astimezone(UTC).isoformat()
                record["period_start_epoch"] = start_epoch
            except (ValueError, OverflowError, OSError) as err:
                raise ValueError("invalid sampled_at") from err
        else:
            raise ValueError("use synced with an aware timestamp or unsynced with null")
        for field, (minimum, maximum) in METRICS.items():
            value = record[field]
            if value is None:
                continue
            if not isinstance(value, dict) or set(value) != {"mean", "min", "max", "count"}:
                raise ValueError(f"{field} requires mean, min, max, count or null")
            if not _integer(value["count"]) or not 1 <= value["count"] <= 100000:
                raise ValueError("count must be 1..100000")
            for statistic in ("mean", "min", "max"):
                number = value[statistic]
                if (type(number) not in (int, float) or not minimum <= number <= maximum
                        or not math.isfinite(number)):
                    raise ValueError(f"invalid {field} {statistic}")
            if not value["min"] <= value["mean"] <= value["max"]:
                raise ValueError("require min <= mean <= max")
        normalized.append(record)
    return Batch(device_id, data["session_id"], tuple(normalized))


def is_fresh(record: dict | None, now: float, stale_after: int) -> bool:
    if record is None or record["sampled_epoch"] is None:
        return False
    return -30 <= now - record["sampled_epoch"] <= stale_after


class UploadStore:
    """Permanent minute records, scoped by device; never writes Recorder tables."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS minute_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    received_at REAL NOT NULL,
                    sampled_epoch REAL,
                    has_data INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(device_id, session_id, seq)
                );
                CREATE INDEX IF NOT EXISTS minute_records_device_id ON minute_records(device_id, sampled_epoch);
                CREATE INDEX IF NOT EXISTS minute_records_received_at ON minute_records(received_at);
                CREATE TABLE IF NOT EXISTS current_minute (
                    device_id TEXT PRIMARY KEY,
                    sample_id INTEGER NOT NULL REFERENCES minute_records(id)
                );
            """)

    @staticmethod
    def _latest(db, device_id):
        row = db.execute(
            "SELECT s.payload, s.received_at FROM minute_records s JOIN current_minute c "
            "ON c.sample_id=s.id WHERE c.device_id=?", (device_id,)
        ).fetchone()
        return {**json.loads(row[0]), "received_at": row[1]} if row else None

    def latest(self, device_id: str) -> dict | None:
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            return self._latest(db, device_id)

    def save(self, batch: Batch, now: float, stale_after: int) -> dict:
        inserted, duplicates, updated = 0, 0, False
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = self._latest(db, batch.device_id)
            for record in batch.records:
                sample = {**record, "device_id": batch.device_id, "session_id": batch.session_id}
                canonical = json.dumps(sample, sort_keys=True, separators=(",", ":"), allow_nan=False)
                previous = db.execute(
                    "SELECT payload FROM minute_records WHERE device_id=? AND session_id=? AND seq=?",
                    (batch.device_id, batch.session_id, record["seq"])
                ).fetchone()
                if previous:
                    if previous[0] != canonical:
                        raise ConflictError("existing sequence has different contents")
                    duplicates += 1
                    continue
                cursor = db.execute(
                    "INSERT INTO minute_records(device_id,session_id,seq,received_at,sampled_epoch,has_data,payload) VALUES(?,?,?,?,?,?,?)",
                    (batch.device_id, batch.session_id, record["seq"], now, record["sampled_epoch"],
                     int(any(record[field] is not None for field in METRICS)), canonical)
                )
                inserted += 1
                if not is_fresh(sample, now, stale_after):
                    continue
                if current:
                    if sample["sampled_epoch"] < current["sampled_epoch"]:
                        continue
                    if batch.session_id == current["session_id"]:
                        if sample["seq"] <= current["seq"]:
                            continue
                    elif sample["sampled_epoch"] == current["sampled_epoch"]:
                        continue
                db.execute(
                    "INSERT INTO current_minute(device_id,sample_id) VALUES(?,?) "
                    "ON CONFLICT(device_id) DO UPDATE SET sample_id=excluded.sample_id",
                    (batch.device_id, cursor.lastrowid)
                )
                current, updated = sample, True
        # The connection's transaction has committed before acknowledging records.
        return {"accepted": [r["seq"] for r in batch.records], "inserted": inserted,
                "duplicates": duplicates, "current_updated": updated}


    def history(self, device_id: str, start: float, end: float) -> list[dict]:
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            rows = db.execute(
                "SELECT payload FROM minute_records WHERE device_id=? "
                "AND sampled_epoch>=? AND sampled_epoch<=? ORDER BY sampled_epoch,id LIMIT 50001",
                (device_id, start, end),
            ).fetchall()
        if len(rows) > 50000:
            raise ValueError("too many points; choose a shorter time range")
        return [json.loads(row[0]) for row in rows]

    def latest_trip(self, device_id: str) -> list[dict]:
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            latest = db.execute(
                "SELECT MAX(sampled_epoch) FROM minute_records WHERE device_id=?",
                (device_id,),
            ).fetchone()[0]
        if latest is None:
            return []
        points = self.history(device_id, latest - 86400, latest)
        start = 0
        for index in range(1, len(points)):
            if points[index]["sampled_epoch"] - points[index-1]["sampled_epoch"] > 300:
                start = index
        return points[start:]
