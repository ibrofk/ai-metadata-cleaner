from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import piexif
from PIL import Image, ImageCms, PngImagePlugin
from click.testing import CliRunner

from m_c.cli.ai_clean import ai_clean
from m_c.core.ai_cleaner import AIImageCleaner, AIImageCleanerError
from m_c.core.file_utils import get_file_checksum
from m_c.core.tool_bootstrap import ToolBootstrapError, resolve_exiftool

try:
    EXIFTOOL = resolve_exiftool(auto_bootstrap=False)
except ToolBootstrapError:
    EXIFTOOL = None


@unittest.skipUnless(EXIFTOOL, "ExifTool is not available")
class TestAIImageCleaner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="metadata-cleaner-ai-")
        self.root = Path(self.temp_dir.name)
        self.cleaner = AIImageCleaner(exiftool_path=EXIFTOOL, auto_bootstrap=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_exiftool(self, *arguments: str) -> None:
        result = subprocess.run(
            [str(EXIFTOOL), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def _write_jpeg(self) -> Path:
        path = self.root / "camera.jpg"
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        exif = {
            "0th": {
                piexif.ImageIFD.Make: b"Private Camera",
                piexif.ImageIFD.Model: b"AI Fixture 1",
                piexif.ImageIFD.Software: b"Stable Diffusion Fixture",
            },
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: b"2026:08:01 12:00:00",
            },
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"N",
                piexif.GPSIFD.GPSLatitude: ((30, 1), (2, 1), (10, 1)),
                piexif.GPSIFD.GPSLongitudeRef: b"E",
                piexif.GPSIFD.GPSLongitude: ((31, 1), (14, 1), (20, 1)),
            },
            "1st": {},
            "thumbnail": None,
        }
        Image.new("RGB", (24, 16), "red").save(
            path,
            format="JPEG",
            quality=95,
            exif=piexif.dump(exif),
            icc_profile=profile,
        )
        self._run_exiftool(
            "-XMP:Description=AI prompt fixture",
            "-IPTC:Caption-Abstract=Private caption",
            "-Comment=Stable Diffusion seed 123",
            "-overwrite_original",
            str(path),
        )
        data = path.read_bytes()
        fake_jumbf = b"fake-c2pa-jumbf"
        segment = b"\xff\xeb" + (len(fake_jumbf) + 2).to_bytes(2, "big") + fake_jumbf
        path.write_bytes(data[:2] + segment + data[2:])
        return path

    def _write_png(self) -> Path:
        path = self.root / "generated.png"
        info = PngImagePlugin.PngInfo()
        info.add_text(
            "parameters",
            "prompt: a private prompt\nnegative prompt: blur\n"
            "Steps: 20, Sampler: Euler, CFG scale: 7, Seed: 123, Model hash: abc123",
        )
        info.add_text("workflow", '{"nodes": [{"type": "KSampler"}]}')
        Image.new("RGBA", (18, 12), (20, 40, 60, 180)).save(
            path,
            format="PNG",
            pnginfo=info,
        )
        self._run_exiftool(
            "-XMP:Description=PNG XMP fixture",
            "-Comment=PNG comment fixture",
            "-overwrite_original",
            str(path),
        )
        return path

    def test_jpeg_removes_exif_gps_xmp_iptc_icc_and_jumbf(self):
        source = self._write_jpeg()
        original_bytes = source.read_bytes()
        sidecar = source.with_suffix(".xmp")
        sidecar.write_text("keep this sidecar", encoding="utf-8")
        output = self.root / "cleaned" / source.name

        result = self.cleaner.clean(source, output)

        self.assertTrue(result.verification.ok)
        self.assertTrue(output.exists())
        self.assertEqual(source.read_bytes(), original_bytes)
        self.assertEqual(sidecar.read_text(encoding="utf-8"), "keep this sidecar")
        self.assertEqual(result.before.width, result.after.width)
        self.assertEqual(result.before.height, result.after.height)
        self.assertNotIn("jpeg_app:11", result.verification.remaining_findings)

    def test_png_removes_stable_diffusion_text_and_other_ancillary_chunks(self):
        source = self._write_png()
        output = self.root / "cleaned" / source.name

        result = self.cleaner.clean(source, output)

        self.assertTrue(result.verification.ok)
        self.assertEqual(result.before.width, result.after.width)
        self.assertEqual(result.before.height, result.after.height)
        self.assertEqual(result.before.has_alpha, result.after.has_alpha)

    def test_privacy_transform_reencodes_and_changes_binary_hash(self):
        source = self._write_png()
        output = self.root / "cleaned" / source.name

        result = self.cleaner.clean(source, output, privacy_transform=True)

        self.assertEqual(result.cleanup_method, "exiftool+reencode")
        self.assertNotEqual(
            get_file_checksum(str(source)),
            get_file_checksum(str(output)),
        )
        self.assertEqual(result.before.width, result.after.width)
        self.assertEqual(result.before.height, result.after.height)

    def test_animated_webp_keeps_frame_count(self):
        source = self.root / "animated.webp"
        first = Image.new("RGBA", (12, 12), (255, 0, 0, 255))
        second = Image.new("RGBA", (12, 12), (0, 0, 255, 255))
        first.save(
            source,
            format="WEBP",
            save_all=True,
            append_images=[second],
            duration=[40, 40],
            loop=0,
        )
        output = self.root / "cleaned" / source.name

        result = self.cleaner.clean(source, output)

        self.assertTrue(result.verification.ok)
        self.assertEqual(result.before.frame_count, 2)
        self.assertEqual(result.after.frame_count, 2)

    def test_unsupported_deep_format_fails_without_output(self):
        source = self.root / "invalid.avif"
        source.write_bytes(b"not an AVIF")
        output = self.root / "cleaned" / source.name

        with self.assertRaises(AIImageCleanerError):
            self.cleaner.clean(source, output)
        self.assertFalse(output.exists())

    def test_cli_returns_json_summary_and_keeps_sidecar(self):
        source = self._write_png()
        source.with_suffix(".json").write_text('{"keep": true}', encoding="utf-8")
        output_dir = self.root / "batch-output"
        runner = CliRunner()

        result = runner.invoke(
            ai_clean,
            [str(source), "--output", str(output_dir / source.name), "--json-summary"],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["succeeded"], 1)
        self.assertTrue(Path(payload["files"][0]["output"]).exists())
        self.assertEqual(
            source.with_suffix(".json").read_text(encoding="utf-8"), '{"keep": true}'
        )
