#!/usr/bin/env python3
"""Generate an AIR-only NotifyEvent override without editing managed components."""

import argparse
import hashlib
import sys
from pathlib import Path


VENDOR_SHA256 = "9910bc77682f4adf2c885a5a21ac6d75b8958fffac5ac4b72e058fa4393fe8f5"
NOTIFY_EVENT = '''void WifiManager::NotifyEvent(WifiEvent event, const std::string& data) {
    static air::WifiEventDispatcher dispatcher(
        [this](WifiEvent pending, const std::string& payload) {
            std::function<void(WifiEvent, const std::string&)> callback;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                callback = event_callback_;
            }
            if (callback)
                callback(pending, payload);
        });
    dispatcher.Publish(event, data);
}
'''


def generate(source: Path, output: Path) -> None:
    if source.resolve() == output.resolve() or any(
        part in {"managed_components", "components"} for part in output.resolve().parts
    ):
        raise ValueError("output must be a generated copy outside managed/vendor directories")
    original = source.read_bytes()
    actual = hashlib.sha256(original).hexdigest()
    if actual != VENDOR_SHA256:
        raise ValueError(f"vendor SHA256 mismatch: expected {VENDOR_SHA256}, got {actual}")
    text = original.decode("utf-8")
    start = text.index("void WifiManager::NotifyEvent(")
    end = text.index("\nbool WifiManager::Initialize(", start)
    text = text[:start] + NOTIFY_EVENT + text[end:]
    text = text.replace('#include "wifi_manager.h"',
                        '#include "wifi_manager.h"\n#include "air_wifi_events.h"', 1)
    generated = text.encode("utf-8")
    if not output.exists() or output.read_bytes() != generated:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(generated)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        generate(args.source, args.output)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
