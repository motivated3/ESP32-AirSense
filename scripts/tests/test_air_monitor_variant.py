import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("air_build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class AirMonitorVariantTests(unittest.TestCase):
    def test_variant_has_unique_v1_identity_and_s3_target(self):
        variants = build._collect_variants(idf_version=(6, 1, 0))
        matches = [v for v in variants if v["name"] == "waveshare-air-monitor-1.8-v1"]
        self.assertEqual(len(matches), 1)
        variant = matches[0]
        self.assertEqual(variant["board"], "custom/waveshare-air-monitor-1.8-v1")
        self.assertEqual(variant["type"], "waveshare-air-monitor-1.8-v1")
        self.assertEqual(variant["target"], "esp32s3")
        self.assertEqual(variant["config"], "CONFIG_BOARD_TYPE_WAVESHARE_AIR_MONITOR_1_8_V1")

    def test_air_variant_validates_flash_images_on_every_boot(self):
        config = json.loads((ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1/config.json").read_text())
        options = config["builds"][0]["sdkconfig_append"]
        for flag in ("ALWAYS", "ON_POWER_ON", "IN_DEEP_SLEEP"):
            self.assertIn(f"CONFIG_BOOTLOADER_SKIP_VALIDATE_{flag}=n", options)

    def test_air_build_consumes_smooth_animation_refresh_period(self):
        with (
            mock.patch.object(build, "_prepare_target"),
            mock.patch.object(build, "_configure_build") as configure,
            mock.patch.object(build, "_validate_configured_symbols"),
            mock.patch.object(build, "_validate_configured_options"),
            mock.patch.object(build, "_run_idf"),
            mock.patch.object(build, "merge_bin"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            build.build_board(
                "custom/waveshare-air-monitor-1.8-v1",
                name_filter="waveshare-air-monitor-1.8-v1",
                idf_version=(6, 1, 0),
            )
        configure.assert_called_once()
        options = build._sdkconfig_assignments(configure.call_args.args[1])
        self.assertEqual(options.get("CONFIG_LV_DEF_REFR_PERIOD"), "16")

    def test_original_v1_still_resolves_to_original_identity(self):
        variants = build._collect_variants(idf_version=(6, 1, 0))
        original = next(v for v in variants if v["name"] == "esp32-s3-touch-amoled-1.8")
        self.assertEqual(original["board"], "waveshare/esp32-s3-touch-amoled-1.8")
        self.assertEqual(original["type"], "esp32-s3-touch-amoled-1.8")


if __name__ == "__main__":
    unittest.main()
