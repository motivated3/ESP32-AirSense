"""Minute upload contract, real SQLite persistence, and vehicle data gaps."""

from datetime import datetime
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'custom_components/air_monitor/core.py'
spec = importlib.util.spec_from_file_location('air_monitor_core', SOURCE)
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)
NOW = datetime.fromisoformat('2026-10-24T08:00:00+00:00').timestamp()


def metric(value=800, low=None, high=None, count=12):
    return {'mean': value, 'min': value if low is None else low,
            'max': value if high is None else high, 'count': count}


def payload(seq=1, age=0, **changes):
    record = {'seq': seq, 'period_start': datetime.fromtimestamp(NOW-age-59, core.UTC).isoformat(),
              'sampled_at': datetime.fromtimestamp(NOW-age, core.UTC).isoformat(),
              'uptime_ms': seq*60000, 'clock_quality': 'synced',
              'co2_ppm': metric(), 'hcho_ppb': metric(20, count=60),
              'temperature_c': metric(24.5), 'humidity_pct': metric(45)}
    record.update(changes)
    return {'schema_version': 2, 'device_id': 'air_monitor_01',
            'session_id': 'boot-1', 'records': [record]}


class ValidationTests(unittest.TestCase):
    def test_minute_statistics_and_null_are_preserved(self):
        batch = core.validate_batch(payload(co2_ppm=metric(800, 600, 1100), hcho_ppb=None), 'air_monitor_01', NOW)
        self.assertEqual(batch.records[0]['co2_ppm'], metric(800, 600, 1100))
        self.assertIsNone(batch.records[0]['hcho_ppb'])

    def test_rejects_bad_aggregate_values_counts_and_units(self):
        invalid = [True, 800, '800', metric(True), metric(float('nan')), metric(10**400),
                   metric(399), metric(800, 900, 1000), metric(800, 600, 700),
                   metric(count=0), metric(count=True), {**metric(), 'unit': 'ppm'}]
        for value in invalid:
            with self.subTest(value=str(value)[:80]), self.assertRaises(ValueError):
                core.validate_batch(payload(co2_ppm=value), 'air_monitor_01', NOW)

    def test_rejects_invalid_envelopes(self):
        for field,value in [('device_id','other'),('session_id','../bad'),('schema_version',1),
                            ('schema_version',True),('records',[]),('records',[payload()['records'][0]]*101)]:
            data=payload(); data[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                core.validate_batch(data,'air_monitor_01',NOW)
        data=payload(); data['records']*=2
        with self.assertRaises(ValueError): core.validate_batch(data,'air_monitor_01',NOW)

    def test_interval_requires_aware_real_times_and_at_most_sixty_seconds(self):
        invalid=[dict(sampled_at='garbage'),dict(sampled_at='2026-10-24T08:00:00'),
                 dict(sampled_at='2099-01-01T00:00:00Z'),dict(period_start='2026-10-24T07:58:00Z'),
                 dict(period_start='2026-10-24T08:00:01Z'),dict(seq=-1),dict(uptime_ms=True)]
        for changes in invalid:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                core.validate_batch(payload(**changes),'air_monitor_01',NOW)
        # A final partial interval is accepted when it was actually uploaded.
        core.validate_batch(payload(period_start='2026-10-24T07:59:50Z'),'air_monitor_01',NOW)

    def test_unsynced_times_are_explicit_and_not_live(self):
        batch=core.validate_batch(payload(period_start=None,sampled_at=None,clock_quality='unsynced'), 'air_monitor_01', NOW)
        self.assertFalse(core.is_fresh(batch.records[0],NOW,120))

    def test_device_auth_is_scoped(self):
        devices={'air_monitor_01':{'key_sha256':hashlib.sha256(b'test-key').hexdigest()}}
        self.assertTrue(core.authenticate(devices,'air_monitor_01','Bearer test-key'))
        for device,header in [('other','Bearer test-key'),('air_monitor_01',None),('air_monitor_01','Bearer wrong')]:
            self.assertFalse(core.authenticate(devices,device,header))


class MinuteStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'minutes.sqlite3'
        self.store=core.UploadStore(self.path); self.store.initialize()

    def save(self,data,now=NOW):
        return self.store.save(core.validate_batch(data,'air_monitor_01',now),now,120)

    def test_commit_then_ack_and_retry_does_not_duplicate_history(self):
        first=self.save(payload()); retry=self.save(payload())
        self.assertEqual(first['accepted'],[1]); self.assertEqual(first['inserted'],1)
        self.assertEqual(retry['duplicates'],1); self.assertFalse(retry['current_updated'])
        self.assertEqual(len(self.store.history('air_monitor_01',NOW-100,NOW+1)),1)

    def test_conflict_rolls_back_whole_batch(self):
        self.save(payload())
        data=payload(seq=2); data['records'].append(payload(co2_ppm=metric(900))['records'][0])
        with self.assertRaises(core.ConflictError): self.save(data)
        self.assertEqual(len(self.store.history('air_monitor_01',NOW-100,NOW+1)),1)
        self.assertEqual(self.store.latest('air_monitor_01')['co2_ppm']['mean'],800)

    def test_old_backfill_is_preserved_at_original_time_without_becoming_current(self):
        self.save(payload(age=3600))
        self.assertIsNone(self.store.latest('air_monitor_01'))
        points=self.store.history('air_monitor_01',NOW-4000,NOW)
        self.assertEqual(points[0]['sampled_epoch'],NOW-3600)

    def test_minute_history_survives_a_year_and_restart(self):
        self.save(payload(co2_ppm=metric(800,600,1100)))
        restored=core.UploadStore(self.path); restored.initialize()
        points=restored.history('air_monitor_01',NOW-100,NOW+365*86400)
        self.assertEqual(points[0]['co2_ppm'],metric(800,600,1100))
        self.assertFalse(core.is_fresh(restored.latest('air_monitor_01'),NOW+121,120))

    def test_older_sequence_and_timestamp_do_not_replace_current(self):
        self.save(payload(seq=5,age=1))
        self.assertFalse(self.save(payload(seq=4))['current_updated'])
        self.assertFalse(self.save(payload(seq=6,age=10))['current_updated'])
        self.assertEqual(self.store.latest('air_monitor_01')['seq'],5)

    def test_new_boot_advances_with_null_without_zero_measurement(self):
        self.save(payload(seq=50,age=1)); data=payload(co2_ppm=None); data['session_id']='boot-2'
        self.assertTrue(self.save(data)['current_updated'])
        self.assertIsNone(self.store.latest('air_monitor_01')['co2_ppm'])

    def test_parking_adds_no_points_and_last_partial_uploaded_period_is_preserved(self):
        self.save(payload(period_start='2026-10-24T07:59:50Z'))
        later=NOW+3600
        data=payload(seq=2,period_start=datetime.fromtimestamp(later-59,core.UTC).isoformat(),
                     sampled_at=datetime.fromtimestamp(later,core.UTC).isoformat())
        self.save(data,now=later)
        points=self.store.history('air_monitor_01',NOW-100,later+1)
        self.assertEqual([p['sampled_epoch'] for p in points],[NOW,later])

    def test_unknown_clock_and_all_null_are_not_plotted_as_measurements(self):
        self.save(payload(period_start=None,sampled_at=None,clock_quality='unsynced'))
        self.save(payload(seq=2,co2_ppm=None,hcho_ppb=None,temperature_c=None,humidity_pct=None))
        points=self.store.history('air_monitor_01',NOW-100,NOW+1)
        self.assertEqual(len(points),1)
        self.assertIsNone(points[0]['co2_ppm'])

    def test_explicit_missing_partial_period_is_preserved_as_a_gap_marker(self):
        self.save(payload(seq=1,age=60))
        self.save(payload(seq=2,age=30,co2_ppm=None,hcho_ppb=None,temperature_c=None,humidity_pct=None))
        self.save(payload(seq=3))
        points=self.store.history('air_monitor_01',NOW-100,NOW+1)
        self.assertEqual(len(points),3)
        self.assertIsNone(points[1]['co2_ppm'])

    def test_history_is_scoped_to_device(self):
        self.save(payload())
        self.assertEqual(self.store.history('another_device',NOW-100,NOW+1),[])


if __name__=='__main__': unittest.main()
