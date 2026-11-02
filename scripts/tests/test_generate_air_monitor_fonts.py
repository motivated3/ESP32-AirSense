import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_air_monitor_fonts.py"
ASSETS = ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1/assets"
HAS_FONTTOOLS = importlib.util.find_spec("fontTools") is not None
CONVERTER = os.environ.get("AIR_FONT_CONVERTER")
NODE = os.environ.get("AIR_FONT_NODE", "node")


@unittest.skipUnless(HAS_FONTTOOLS, "requires pinned font-tools environment")
class AirMonitorFontTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated = tempfile.TemporaryDirectory(prefix="air-font-test-")
        cls.addClassCleanup(cls.generated.cleanup)
        cls.default_output = Path(cls.generated.name) / "out"
        cls.default_result = None

    def default_generation(self):
        cls = type(self)
        if cls.default_result is None:
            cls.default_result = self.run_generator(cls.default_output)
        self.assertEqual(cls.default_result.returncode, 0, cls.default_result.stderr)
        return cls.default_output

    def seed_default_generation(self, output):
        shutil.copytree(self.default_generation(), output)

    def run_generator(self, output, *args, env=None):
        command = [sys.executable, str(SCRIPT), "--output", str(output)]
        if CONVERTER:
            command += ["--node", NODE, "--converter", CONVERTER]
        return subprocess.run(command + list(args), capture_output=True, text=True, env=env)

    def test_missing_character_fails_before_any_font_is_written(self):
        # Silently dropping a newly added UI character must fail the build.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            strings = root / "strings.json"
            strings.write_text(json.dumps({"strings": ["甲醛\U0010ffff"]}))
            result = self.run_generator(root / "out", "--strings", str(strings))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing glyph U+10FFFF", result.stderr)
            self.assertFalse(list(root.glob("out/*.c")))

    def test_changed_source_hash_is_rejected(self):
        # A download/cache replacement must not silently change the firmware font.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = json.loads((ASSETS / "fonts.json").read_text())
            for source in manifest["sources"].values():
                source["path"] = str(ASSETS / source["path"])
            manifest["sources"]["roboto"]["sha256"] = "0" * 64
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            result = self.run_generator(root / "out", "--manifest", str(path), "--check-only")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sha256 mismatch", result.stderr)

    def test_chat_input_covers_gb2312_without_online_font_sources(self):
        # Dropping broad Chinese coverage must fail before firmware generation.
        spec = importlib.util.spec_from_file_location("air_fonts", SCRIPT)
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        _, sources, assignments = generator.inputs(ASSETS / "fonts.json", None)
        self.assertIn("font_air_chat_18", assignments)
        points = set().union(*assignments["font_air_chat_18"].values())
        self.assertEqual(sum(0x4E00 <= point <= 0x9FFF for point in points), 6763)
        for character in "龠氦苯霾酚烯烃镍酞醛Ωα→℃，！？�":
            self.assertIn(ord(character), points)
        self.assertTrue(set(range(32, 127)) <= points)
        self.assertNotIn(ord("🙂"), points)
        self.assertNotIn(0x20000, points)
        self.assertTrue(all(source["path"].is_file() for source in sources.values()))

    @unittest.skipUnless(CONVERTER, "set AIR_FONT_CONVERTER for real conversion")
    def test_chat_font_has_readable_offline_chinese_with_bounded_bitmap(self):
        # Wrong charset/bpp or a dropped declaration breaks real chat rendering.
        output = self.default_generation()
        self.assertTrue((output / "font_air_chat_18.c").exists())
        metrics = json.loads((output / "font_metrics.json").read_text())
        chat = metrics["fonts"]["font_air_chat_18"]
        self.assertEqual(chat["size"], 18)
        self.assertEqual(chat["bpp"], 2)
        self.assertLessEqual(chat["bitmap_bytes"], 750_000)
        for character in "龠氦苯霾酚烯烃镍酞醛":
            glyph = chat["glyphs"][f"U+{ord(character):04X}"]
            self.assertGreater(glyph["advance"], 12)
            self.assertGreater(glyph["box"][0], 8)
            self.assertGreater(glyph["box"][1], 8)
        self.assertIn("LV_FONT_DECLARE(font_air_chat_18)", (output / "air_fonts.h").read_text())
        self.assertIn(".bpp = 2", (output / "font_air_chat_18.c").read_text())
        for role in ["font_air_text_18", "font_air_text_20"]:
            self.assertEqual(metrics["fonts"][role]["bpp"], 4)
            for character in "小智对话本次在线离线正在连接聆听思考回复结束开始说停止回到最新你我车内空气暂无记录语音已关闭请先":
                self.assertIn(f"U+{ord(character):04X}", metrics["fonts"][role]["glyphs"])

    @unittest.skipUnless(CONVERTER, "set AIR_FONT_CONVERTER for real conversion")
    def test_hcho_digits_fit_four_digit_card(self):
        # Use actual converted advances for the 2000 ppb reading in its 94px card.
        output = self.default_generation()
        self.assertTrue((output / "font_air_digits_64.c").exists())
        metrics = json.loads((output / "font_metrics.json").read_text())
        font = metrics["fonts"]["font_air_digits_64"]
        width = sum(font["glyphs"][f"U+{ord(c):04X}"]["advance"] for c in "2000")
        self.assertLessEqual(width, 132)
        self.assertGreater(font["line_height"], 30)
        self.assertLessEqual(font["line_height"], 52)
        advances = {font["glyphs"][f"U+{ord(c):04X}"]["advance"] for c in "0123456789"}
        self.assertEqual(len(advances), 1, "measurement digits must remain tabular")

    @unittest.skipUnless(CONVERTER, "set AIR_FONT_CONVERTER for real conversion")
    def test_large_home_digits_fit_four_digit_container(self):
        # The reference's large home value must fit 0–9999 without shrinking.
        output = self.default_generation()
        self.assertTrue((output / "font_air_digits_120.c").exists())
        metrics = json.loads((output / "font_metrics.json").read_text())
        font = metrics["fonts"]["font_air_digits_120"]
        self.assertGreater(font["line_height"], 80)
        self.assertLessEqual(font["text_widths"]["5000"], 250)
        advances = {font["glyphs"][f"U+{ord(c):04X}"]["advance"] for c in "0123456789"}
        self.assertEqual(len(advances), 1, "measurement digits must remain tabular")

    @unittest.skipUnless(CONVERTER, "set AIR_FONT_CONVERTER for real conversion")
    def test_cached_unicode_metrics_load_under_non_utf8_locale(self):
        # A C-locale build must still load cached °C/— strings as UTF-8.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            self.seed_default_generation(output)
            first = self.run_generator(output)
            self.assertEqual(first.returncode, 0, first.stderr)
            env = dict(os.environ, LC_ALL="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
            second = self.run_generator(output, env=env)
            self.assertEqual(second.returncode, 0, second.stderr)

    @unittest.skipUnless(CONVERTER, "set AIR_FONT_CONVERTER for real conversion")
    def test_second_generation_keeps_contents_and_mtimes(self):
        # Reconfiguring CMake must not rebuild identical generated font files.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            self.seed_default_generation(output)
            first = self.run_generator(output)
            self.assertEqual(first.returncode, 0, first.stderr)
            before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir() if p.is_file()}
            self.assertIn("font_air_digits_88.c", before)
            self.assertIn("air_fonts.h", before)
            second = self.run_generator(output)
            self.assertEqual(second.returncode, 0, second.stderr)
            after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir() if p.is_file()}
            self.assertEqual(before, after)
            elsewhere = Path(directory) / "another-build-directory"
            third = self.run_generator(elsewhere)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertEqual(
                {name: data for name, (data, _) in before.items()},
                {p.name: p.read_bytes() for p in elsewhere.iterdir() if p.is_file()},
            )
            metrics = json.loads((output / "font_metrics.json").read_text())
            main = metrics["fonts"]["font_air_digits_88"]
            advances = {main["glyphs"][f"U+{ord(c):04X}"]["advance"] for c in "0123456789"}
            self.assertEqual(len(advances), 1, "measurement digits must remain tabular")
            self.assertLessEqual(main["text_widths"]["65535"], 230)

    @unittest.skipUnless(CONVERTER, "set AIR_FONT_CONVERTER for real conversion")
    def test_new_ui_character_is_present_in_generated_metrics(self):
        # Cache keys must include the strings, not only the source font hash.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            self.seed_default_generation(output)
            strings = root / "strings.json"
            original = json.loads((ASSETS / "ui_strings.json").read_text())
            strings.write_text(json.dumps(original))
            first = self.run_generator(output, "--strings", str(strings))
            self.assertEqual(first.returncode, 0, first.stderr)
            old = (output / "font_air_text_18.c").read_bytes()
            chat = (output / "font_air_chat_18.c").stat().st_mtime_ns
            original["strings"].append("汉")
            strings.write_text(json.dumps(original))
            second = self.run_generator(output, "--strings", str(strings))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotEqual(old, (output / "font_air_text_18.c").read_bytes())
            self.assertEqual(chat, (output / "font_air_chat_18.c").stat().st_mtime_ns)
            metrics = json.loads((output / "font_metrics.json").read_text())
            self.assertIn("U+6C49", metrics["fonts"]["font_air_text_18"]["glyphs"])


if __name__ == "__main__":
    unittest.main()
