import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1]/'generate_air_ha_config.py'

class AirHaConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('ha_config', SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_missing_disables_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            text = self.module.generate(Path(directory)/'missing.json')
            self.assertIn('kEnabled = false', text)

    def test_valid_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'credentials.json'
            source.write_text(json.dumps(dict(endpoint='https://example.org:12123/api/air_monitor/ingest',
                device_id='air_monitor_01',upload_key='test-key-'+'a'*32)))
            source.chmod(0o600)
            text = self.module.generate(source)
            self.assertIn('kEnabled = true',text)
            self.assertIn('air_monitor_01',text)
            source.chmod(0o644)
            with self.assertRaises(ValueError): self.module.generate(source)

    def test_reject_insecure_or_header_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'credentials.json'
            for changes in (dict(endpoint='http://example.org/ingest'),dict(endpoint='https://user:pass@example.org/x'),
                            dict(endpoint='https://example.org/x?key=secret'),dict(device_id='bad\r\nid'),
                            dict(upload_key='bad\r\nkey'),dict(endpoint='https://example.org/x#fragment'),
                            dict(device_id='_invalid'),dict(device_id='-invalid')):
                value=dict(endpoint='https://example.org/ingest',device_id='air_monitor_01',upload_key='a'*40)
                value.update(changes); source.write_text(json.dumps(value));source.chmod(0o600)
                with self.subTest(changes=list(changes)),self.assertRaises(ValueError): self.module.generate(source)

if __name__=='__main__': unittest.main()
