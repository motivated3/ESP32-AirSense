#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

: "${IDF_PATH:?Source the pinned ESP-IDF export.sh first}"
command -v node >/dev/null
command -v npm >/dev/null

air_tools_dir="${AIR_FONT_TOOLS_DIR:-$PWD/.air-font-tools}"
air_assets="$PWD/main/boards/custom/waveshare-air-monitor-1.8-v1/assets"
if [[ ! -x "$air_tools_dir/python/bin/python" ]]; then
    python3 -m venv "$air_tools_dir/python"
fi
"$air_tools_dir/python/bin/python" -m pip install --disable-pip-version-check -r "$air_assets/font-tools-requirements.txt"
mkdir -p "$air_tools_dir/npm"
cp "$air_assets/font-tools-package.json" "$air_tools_dir/npm/package.json"
cp "$air_assets/font-tools-package-lock.json" "$air_tools_dir/npm/package-lock.json"
npm ci --prefix "$air_tools_dir/npm" --ignore-scripts --no-audit --no-fund
export AIR_FONT_PYTHON="$air_tools_dir/python/bin/python"
export AIR_FONT_CONVERTER="$air_tools_dir/npm/node_modules/lv_font_conv/lv_font_conv.js"
python scripts/build.py custom/waveshare-air-monitor-1.8-v1 --name waveshare-air-monitor-1.8-v1 --language zh-CN "$@"
