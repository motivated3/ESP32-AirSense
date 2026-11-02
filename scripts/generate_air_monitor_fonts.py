#!/usr/bin/env python3
"""Generate the air monitor's pinned, offline LVGL C fonts (never download)."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1/assets"
FONTTOOLS_VERSION = "4.56.0"
CONVERTER_VERSION = "1.5.3"
SAMPLES = ["864", "999", "1000", "5000", "40000", "65535", "—", "18", "6554", "25.4°C", "-40.0°C", "100%"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_changed(path, text):
    data = text.encode("utf-8")
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def ranges(codepoints):
    runs = []
    for point in sorted(codepoints):
        if runs and point == runs[-1][1] + 1:
            runs[-1][1] = point
        else:
            runs.append([point, point])
    return ",".join(f"0x{a:x}" if a == b else f"0x{a:x}-0x{b:x}" for a, b in runs)


def inputs(manifest_path, strings_path):
    import fontTools
    from fontTools.ttLib import TTFont

    if fontTools.__version__ != FONTTOOLS_VERSION:
        raise ValueError(f"requires fonttools=={FONTTOOLS_VERSION}, found {fontTools.__version__}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = {}
    for name, info in manifest["sources"].items():
        path = manifest_path.parent / info["path"]
        if digest(path.read_bytes()) != info["sha256"]:
            raise ValueError(f"sha256 mismatch: {name}")
        with TTFont(path, lazy=True) as font:
            sources[name] = dict(info, path=path, coverage=set(font.getBestCmap()))
    path = strings_path or manifest_path.parent / manifest["strings_file"]
    strings = json.loads(path.read_text(encoding="utf-8"))
    strings = strings["strings"] if isinstance(strings, dict) else strings
    if not isinstance(strings, list) or not all(isinstance(s, str) for s in strings):
        raise ValueError("UI strings must be a JSON string list")
    text = unicodedata.normalize("NFC", "".join(strings) + manifest["text_extra"])
    charsets = {
        "text": set(range(32, 127)) | {ord(c) for c in text if c not in "\r\n\t"},
        "numeric": {ord(c) for c in manifest["numeric_characters"]},
    }
    # GB2312 has 6763 Han characters and 682 symbols; Python's built-in codec
    # provides a fixed offline repertoire without bundling another source file.
    charsets["chat"] = charsets["text"] | {
        ord(character)
        for lead in range(0xA1, 0xF8)
        for trail in range(0xA1, 0xFF)
        for character in bytes([lead, trail]).decode("gb2312", errors="ignore")
    } | {ord(character) for character in manifest.get("chat_extra", "�")}
    assignments = {}
    for profile in manifest["profiles"]:
        remaining = set(charsets[profile["charset"]])
        assigned = {}
        for source in [profile["source"], profile.get("fallback")]:
            if source:
                owned = remaining & sources[source]["coverage"]
                if owned:
                    assigned[source] = owned
                    remaining -= owned
        if remaining:
            missing = ", ".join(f"missing glyph U+{c:04X}" for c in sorted(remaining))
            raise ValueError(f"{profile['name']}: {missing}")
        assignments[profile["name"]] = assigned
    return manifest, sources, assignments


def prepare_font(source, points, weight, destination):
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    with TTFont(source, recalcTimestamp=False) as font:
        if "fvar" in font:
            instantiateVariableFont(font, {"wght": weight}, inplace=True)
        options = subset.Options()
        options.layout_features = []  # UI text has no shaping; numeric advances stay tabular.
        options.recalc_timestamp = False
        sub = subset.Subsetter(options=options)
        sub.populate(unicodes=points)
        sub.subset(font)
        font.recalcTimestamp = False
        font.save(destination)


def c_metrics(text, codepoints):
    """Read the actual converter's 1/16px advances, not desktop estimates."""
    fields = lambda s: {k: int(v) for k, v in re.findall(r"\.(\w+)\s*=\s*(-?\d+)", s)}
    descriptors = re.search(r"glyph_dsc\[\]\s*=\s*\{(.*?)\n\};", text, re.S)
    glyphs = [fields(s) for s in re.findall(r"\{([^{}]+)\}", descriptors[1])]
    arrays = {
        name: [int(n, 0) for n in re.findall(r"0x[\da-fA-F]+|\b\d+\b", body)]
        for name, body in re.findall(r"static const uint(?:8|16)_t (\w+)\[\]\s*=\s*\{(.*?)\};", text, re.S)
    }
    cmaps = re.search(r"cmaps\[\]\s*=\s*\{(.*?)\n\};", text, re.S)
    result = {}
    for point in sorted(codepoints):
        for cmap in re.findall(r"\{([^{}]+)\}", cmaps[1]):
            info = fields(cmap)
            offset = point - info["range_start"]
            if not 0 <= offset < info["range_length"]:
                continue
            unicode_list = re.search(r"\.unicode_list\s*=\s*(\w+)", cmap)[1]
            if unicode_list != "NULL":
                if offset not in arrays[unicode_list]:
                    continue
                offset = arrays[unicode_list].index(offset)
            offsets = re.search(r"\.glyph_id_ofs_list\s*=\s*(\w+)", cmap)[1]
            if offsets != "NULL":
                offset = arrays[offsets][offset]
            item = glyphs[info["glyph_id_start"] + offset]
            result[f"U+{point:04X}"] = {
                "advance": item["adv_w"] / 16,
                "box": [item[k] for k in ["box_w", "box_h", "ofs_x", "ofs_y"]],
            }
            break
        if f"U+{point:04X}" not in result:
            raise ValueError(f"converter omitted glyph U+{point:04X}")
    widths = {
        sample: sum(result[f"U+{ord(c):04X}"]["advance"] for c in sample)
        for sample in SAMPLES if all(ord(c) in codepoints for c in sample)
    }
    bitmap = re.search(r"glyph_bitmap\[\]\s*=\s*\{(.*?)\};", text, re.S)[1]
    return {
        "line_height": int(re.search(r"\.line_height\s*=\s*(\d+)", text)[1]),
        "base_line": int(re.search(r"\.base_line\s*=\s*(\d+)", text)[1]),
        "bitmap_bytes": len(re.findall(r"0x[\da-fA-F]+", bitmap)),
        "glyphs": result,
        "text_widths": widths,
    }


def generate(args, manifest, sources, assignments):
    converter = Path(args.converter or shutil.which("lv_font_conv") or "").resolve()
    package = converter.parent / "package.json"
    if not converter.is_file() or not package.is_file():
        raise ValueError("set --converter to the pinned lv_font_conv/lv_font_conv.js")
    if json.loads(package.read_text(encoding="utf-8"))["version"] != CONVERTER_VERSION:
        raise ValueError(f"requires lv_font_conv=={CONVERTER_VERSION}")
    lock_path = ASSETS / "font-tools-package-lock.json"
    tool_hash = digest(Path(__file__).read_bytes() + lock_path.read_bytes())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache_path = output / ".font-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    next_cache, metrics = {}, {}
    with tempfile.TemporaryDirectory(prefix="air-fonts-") as directory:
        temp = Path(directory)
        prepared = {}
        pending = {}
        for profile in manifest["profiles"]:
            name = profile["name"]
            assigned = assignments[name]
            points = set().union(*assigned.values())
            fingerprint = digest(json_text({
                "profile": profile,
                "points": sorted(points),
                "sources": {s: sources[s]["sha256"] for s in assigned},
                "tools": tool_hash,
                "fonttools": FONTTOOLS_VERSION,
                "converter": CONVERTER_VERSION,
            }).encode())
            target = output / f"{name}.c"
            old = cache.get(name, {})
            if old.get("fingerprint") == fingerprint and target.exists() and digest(target.read_bytes()) == old.get("sha256"):
                next_cache[name] = old
                metrics[name] = old["metrics"]
                print(f"cached {name}")
                continue
            command = [args.node, str(converter), "--no-compress", "--no-prefilter", "--no-kerning"]
            for source, owned in assigned.items():
                weight = profile.get("weight", 400)
                key = (source, weight, tuple(sorted(owned)))
                if key not in prepared:
                    path = temp / f"source-{len(prepared)}.otf"
                    prepare_font(sources[source]["path"], owned, weight, path)
                    prepared[key] = path
                command += ["--font", str(prepared[key]), "-r", ranges(owned)]
            generated = temp / f"{name}.c"
            bpp = profile.get("bpp", 4)
            command += ["--format", "lvgl", "--bpp", str(bpp), "--size", str(profile["size"]),
                        "--lv-include", "lvgl.h", "--lv-font-name", name, "-o", str(generated)]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            if completed.returncode:
                raise ValueError(f"converter failed for {name}: {completed.stderr.strip()}")
            content = generated.read_text(encoding="utf-8")
            content = re.sub(r"^ \* Opts:.*$", " * Generated from pinned sources by generate_air_monitor_fonts.py", content, flags=re.M)
            content = "/* Font derivative: OFL-1.1; see board assets/fonts/OFL-*.txt. */\n" + content
            measured = c_metrics(content, points)
            metrics[name] = dict(measured, size=profile["size"], bpp=bpp, source_sha256={s: sources[s]["sha256"] for s in assigned})
            pending[target] = content
            next_cache[name] = dict(fingerprint=fingerprint, sha256=digest(content.encode()), metrics=metrics[name])
            print(f"generated {name}")
        # Publish only after every requested profile has passed conversion and coverage checks.
        for target, content in pending.items():
            write_changed(target, content)
    header = '#pragma once\n#include "lvgl.h"\n#ifdef __cplusplus\nextern "C" {\n#endif\n'
    header += "".join(f"LV_FONT_DECLARE({p['name']});\n" for p in manifest["profiles"])
    header += "#ifdef __cplusplus\n}\n#endif\n"
    write_changed(output / "air_fonts.h", header)
    write_changed(output / "font_metrics.json", json_text({"schema": 1, "kerning": False, "fonts": metrics}))
    write_changed(cache_path, json_text(next_cache))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ASSETS / "fonts.json")
    parser.add_argument("--strings", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "build/generated/air_fonts")
    parser.add_argument("--node", default=os.environ.get("AIR_FONT_NODE", "node"))
    parser.add_argument("--converter", default=os.environ.get("AIR_FONT_CONVERTER"))
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        manifest, sources, assignments = inputs(args.manifest.resolve(), args.strings)
        if args.check_only:
            print(f"validated {len(manifest['profiles'])} profiles")
        else:
            generate(args, manifest, sources, assignments)
    except (ImportError, OSError, ValueError, KeyError) as error:
        print(f"font generation: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
