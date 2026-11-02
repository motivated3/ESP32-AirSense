"""Run the real board font CMake block without a pre-existing output/cache."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CMAKE = os.environ.get("AIR_CMAKE") or shutil.which("cmake")
CONVERTER = os.environ.get("AIR_FONT_CONVERTER")


@unittest.skipUnless(CMAKE and CONVERTER, "requires CMake and pinned font tools")
class CleanAirFontBuildTests(unittest.TestCase):
    def test_clean_configure_creates_include_directory_then_builds_fonts(self):
        source = (ROOT / "main/CMakeLists.txt").read_text()
        start = source.index("\nif(CONFIG_BOARD_TYPE_WAVESHARE_AIR_MONITOR_1_8_V1)") + 1
        block = source[start:source.index("# Select one audio engine", start)]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            assets = temp / "boards/custom/waveshare-air-monitor-1.8-v1/assets"
            assets.parent.mkdir(parents=True)
            assets.symlink_to(ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1/assets", target_is_directory=True)
            (temp / "CMakeLists.txt").write_text(
                'cmake_minimum_required(VERSION 3.16)\nproject(clean_air_fonts NONE)\n'
                'set(CONFIG_BOARD_TYPE_WAVESHARE_AIR_MONITOR_1_8_V1 ON)\n'
                'set(BOARD_DIR "custom/waveshare-air-monitor-1.8-v1")\n'
                f'set(PROJECT_DIR "{ROOT.as_posix()}")\n' + block +
                'foreach(path IN LISTS INCLUDE_DIRS)\n'
                ' if(NOT IS_DIRECTORY "${path}")\n'
                '  message(FATAL_ERROR "IDF include directory is absent: ${path}")\n'
                ' endif()\nendforeach()\n'
                'file(WRITE "${CMAKE_BINARY_DIR}/font_sources.txt" "${AIR_FONT_SOURCES}")\n'
                'add_custom_target(fonts ALL DEPENDS ${AIR_FONT_SOURCES} "${AIR_FONT_OUTPUT}/air_fonts.h")\n'
            )
            output = temp / "build"
            env = dict(os.environ, AIR_FONT_PYTHON=os.sys.executable)
            configured = subprocess.run([CMAKE, "-S", str(temp), "-B", str(output)], env=env,
                                        capture_output=True, text=True)
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            self.assertTrue((output / "generated/air_fonts").is_dir())
            sources = (output / "font_sources.txt").read_text().split(";")
            self.assertIn(str(output / "generated/air_fonts/font_air_chat_18.c"), sources)
            built = subprocess.run([CMAKE, "--build", str(output)], env=env,
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertTrue((output / "generated/air_fonts/air_fonts.h").exists())
            self.assertEqual(len(list((output / "generated/air_fonts").glob("font_air_*.c"))), 9)
            self.assertTrue((output / "generated/air_fonts/font_air_digits_64.c").exists())
            self.assertIn("font_air_digits_64", (output / "generated/air_fonts/air_fonts.h").read_text())
            self.assertTrue((output / "generated/air_fonts/font_air_chat_18.c").exists())
            self.assertIn("font_air_chat_18", (output / "generated/air_fonts/air_fonts.h").read_text())


if __name__ == "__main__":
    unittest.main()
