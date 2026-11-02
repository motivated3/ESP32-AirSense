# Reproducible Jade fonts

These are source resources for the 368×448 air monitor, not full-screen UI images.
`fonts.json` pins the original files by SHA256 and immutable upstream URLs.
`ui_strings.json` is the local UI vocabulary; add every new fixed label/state here.
Generation is offline and fails on a changed source hash or a missing character.

## Sources and licenses

| File | Pinned origin | License |
| --- | --- | --- |
| `fonts/NotoSansSC-Regular.otf` | `notofonts/noto-cjk@523d033d6cb47f4a80c58a35753646f5c3608a78`, `Sans/SubsetOTF/SC/` | OFL-1.1 |
| `fonts/NotoSansSC-Medium.otf` | same commit/directory | OFL-1.1 |
| `fonts/RobotoCondensed-wght.ttf` | `google/fonts@45e3d5269e4a17d823f6d84470bc084dc5ae46f6`, `ofl/robotocondensed/`, v3.008 | OFL-1.1 |

The corresponding copyright/OFL texts are in `fonts/OFL-*.txt`. Retain them in
source and firmware distribution packages. Generated fonts remain OFL font
derivatives; this does not change the license of the firmware code. The upstream
component's Apache license does not replace the source fonts' OFL licenses.

## Tool environment

Use a separate build-tool environment, not system fonts or modified managed
components. FontTools is pinned to 4.56.0. `font-tools-package.json` and
`font-tools-package-lock.json` pin `lv_font_conv` 1.5.3 and its package integrity.
Node 22.19.0 was used for verification.

From the repository root, create an environment outside the source tree:

```sh
FONT_WORK_DIR="$PWD/../../work/font-tools"
python3 -m venv "$FONT_WORK_DIR/venv"
"$FONT_WORK_DIR/venv/bin/python" -m pip install -r main/boards/custom/waveshare-air-monitor-1.8-v1/assets/font-tools-requirements.txt
mkdir -p "$FONT_WORK_DIR/npm"
cp main/boards/custom/waveshare-air-monitor-1.8-v1/assets/font-tools-package.json "$FONT_WORK_DIR/npm/package.json"
cp main/boards/custom/waveshare-air-monitor-1.8-v1/assets/font-tools-package-lock.json "$FONT_WORK_DIR/npm/package-lock.json"
npm ci --prefix "$FONT_WORK_DIR/npm" --ignore-scripts --no-audit --no-fund
```

Run the generator with that Python and the pinned converter:

```sh
"$FONT_WORK_DIR/venv/bin/python" scripts/generate_air_monitor_fonts.py \
  --node node \
  --converter "$FONT_WORK_DIR/npm/node_modules/lv_font_conv/lv_font_conv.js" \
  --output build/generated/air_fonts
```

`--check-only` validates source hashes and coverage without invoking Node or
writing output. `--strings path/to/strings.json` selects an additional caller's
complete string catalog for tests; it replaces the default catalog for that run.
The catalog may be a JSON string list or an object containing `strings`.

Text profiles always retain ASCII U+0020–U+007E plus the fixed UI vocabulary and
the configured symbols/punctuation. Numeric profiles retain digits, decimal and
signs, `—`, `°C`, and `%`; `ppm`/`ppb` use the 18/20px text font. No server-side
glyph push is needed for any fixed UI label. Noto/Roboto fallback selection is
explicit; unsupported characters abort rather than silently disappearing.

## Outputs and CMake contract

Only the generator writes `build/generated/air_fonts/`:

- `font_air_text_18.c`, `font_air_text_20.c`
- `font_air_digits_28.c`, `font_air_digits_36.c`, `font_air_digits_42.c`, `font_air_digits_64.c`, `font_air_digits_88.c`, `font_air_digits_120.c`
- `air_fonts.h` with C/C++ declarations for those eight symbols
- `font_metrics.json` with actual converted advances/bounding boxes and source hashes
- `.font-cache.json` with content fingerprints

CMake can use a custom command listing the eight C files, header and metrics as
outputs, depend on this script, `fonts.json`, `ui_strings.json`, the tool lock and
the three original font files, and add the generated directory to include paths.
Use the pinned FontTools Python for this command. The generator does not edit
CMake, sdkconfig, managed components or vendor files.

Unchanged inputs preserve output bytes and mtimes. Changed labels invalidate
text-font fingerprints. Temporary paths and converter command-line paths are
removed from the generated comment, so separate output directories produce
identical artifacts. Conversion/coverage checks finish before new C files are
published. Kerning and compression are disabled; numeric advances are tabular.

## Verified native metrics

These are the real `lv_font_conv` results, in native pixels, not PNG estimates:

| Font | line height / baseline | Selected widths |
| --- | --- | --- |
| text18 Regular | 21 / 5 | 290 codepoints |
| text20 Medium | 23 / 5 | 290 codepoints |
| digits28, weight600 | 20 / 0 | `25.4°C` 76.9375; `-40.0°C` 86.3125; `100%` 60 |
| digits36, weight600 | 26 / 0 | `18` 36.25; `6554` 72.5 |
| digits42, weight600 | 30 / 0 | `864` 63.375 |
| digits64, weight600 | 47 / 1 | `2000` 128.75; tabular digit advance 32.1875 |
| digits88, weight600 | 65 / 1 | `864` 132.75; `1000`/`5000` 177; five digits 221.25 |
| digits120, weight600 | 88 / 1 | `864` 181.125; four digits 241.5; five digits 301.875 |

The 64px numeric profile uses the same Roboto Condensed weight600 source as the
other numeric profiles. Its four-digit HCHO reading `2000` fits the 136px value
container (including the final 132px-wide value label); its 47px line height
fits the 52px-high label within the 94px card. The `ppb` unit retains the
text font.

Font size is not ink/line height. Position values and units from these metrics;
do not copy the mock PNG's numeric width or clip longer readings. Live LVGL
layout, partition size and physical readability still need integration checks.
Use digits120 for the home CO₂ value 0–9999 and digits88 for five-digit values;
keep the value container and unit baseline fixed when switching fonts. All ten
digits in digits120 advance 60.375px, so any four-digit reading fits within 250px.

Run real conversion tests with the tool environment:

```sh
AIR_FONT_NODE=node \
AIR_FONT_CONVERTER="$FONT_WORK_DIR/npm/node_modules/lv_font_conv/lv_font_conv.js" \
"$FONT_WORK_DIR/venv/bin/python" -m unittest scripts.tests.test_generate_air_monitor_fonts -v
```
