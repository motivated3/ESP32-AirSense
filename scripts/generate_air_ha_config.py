"""Generate a private build header; never print credentials in diagnostics."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit


def generate(source: Path) -> str:
    enabled = source.is_file()
    endpoint = device = key = ''
    if enabled:
        if stat.S_IMODE(source.stat().st_mode) & 0o077:
            raise ValueError('HA credentials must have private permissions (chmod 600)')
        try:
            values = json.loads(source.read_text())
            endpoint, device, key = (values[name] for name in ('endpoint', 'device_id', 'upload_key'))
            if not all(isinstance(v, str) for v in (endpoint, device, key)):
                raise ValueError()
            url = urlsplit(endpoint)
            if (url.scheme != 'https' or not url.hostname or url.username or url.password or
                    url.query or url.fragment or not url.path or not url.port and url.netloc.endswith(':') or
                    any(ord(c) < 33 or ord(c) > 126 for c in endpoint)):
                raise ValueError()
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', device):
                raise ValueError()
            if not re.fullmatch(r'[A-Za-z0-9_.~-]{32,256}', key):
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('Invalid HA credential configuration') from None
    return ('#pragma once\nnamespace air::ha_config {\n'
            f'inline constexpr bool kEnabled = {str(enabled).lower()};\n'
            f'inline constexpr char kEndpoint[] = {json.dumps(endpoint)};\n'
            f'inline constexpr char kDevice[] = {json.dumps(device)};\n'
            f'inline constexpr char kKey[] = {json.dumps(key)};\n'
            '}  // namespace air::ha_config\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        contents = generate(args.input)
    except (ValueError, OSError) as error:
        parser.exit(1, f'HA configuration: {error}\n')
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not args.output.exists() or args.output.read_text() != contents:
        with tempfile.NamedTemporaryFile(mode='w', dir=args.output.parent, delete=False) as stream:
            stream.write(contents)
        os.replace(stream.name, args.output)
    args.output.chmod(0o600)


if __name__ == '__main__':
    main()
