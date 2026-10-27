import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from forensics.detectors import UnavailableDetector
from forensics.pipeline import analyze, decode_image, validate_config


def fixture():
    rng = np.random.default_rng(42)
    pixels = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    output = io.BytesIO()
    Image.fromarray(pixels).save(output, format="PNG")
    return output.getvalue()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.data = fixture()

    def run_analysis(self, config=None, detector=None):
        return analyze(self.data, "fixture.png", config or {}, self.output, detector or UnavailableDetector())

    def test_absent_detector_never_fabricates_scores(self):
        report = self.run_analysis()
        self.assertEqual(len(report["variants"]), 4)
        self.assertTrue(all(v["score"] is None for v in report["variants"]))
        self.assertIsNone(report["summary"]["flip_count"])
        self.assertIn("incomplete", report["summary"]["title"])
        json.dumps(report, allow_nan=False)

    def test_cumulative_parent_and_dimensions(self):
        variants = self.run_analysis({"scale": .75})["variants"]
        self.assertEqual([(v["width"], v["height"]) for v in variants], [(320, 240), (240, 180), (180, 135), (135, 101)])
        for i in range(1, len(variants)):
            self.assertEqual(variants[i]["parent_sha256"], variants[i-1]["sha256"])

    def test_single_pass_control_parent_and_size_match(self):
        cumulative = self.run_analysis()["variants"]
        independent = self.run_analysis({"mode": "independent"})["variants"]
        for i in range(1, len(independent)):
            self.assertEqual(independent[i]["parent_sha256"], independent[0]["sha256"])
            self.assertEqual(independent[i]["width"], cumulative[i]["width"])
            self.assertEqual(independent[i]["height"], cumulative[i]["height"])
        self.assertNotEqual(independent[-1]["sha256"], cumulative[-1]["sha256"])

    def test_jpeg_control_duplicates_are_honest(self):
        variants = self.run_analysis({"mode": "independent", "operation": "jpeg"})["variants"]
        self.assertEqual(variants[1]["sha256"], variants[3]["sha256"])
        self.assertEqual(variants[3]["width"], 320)

    def test_order_is_recorded_and_changes_output(self):
        before = self.run_analysis({"order": "resize-jpeg"})["variants"][1]
        after = self.run_analysis({"order": "jpeg-resize"})["variants"][1]
        self.assertEqual(before["format"], "JPEG")
        self.assertEqual(after["format"], "PNG")
        self.assertEqual([s["type"] for s in after["operations"]], ["jpeg", "resize"])
        self.assertNotEqual(before["mse"], after["mse"])

    def test_invalid_settings_rejected(self):
        for settings in [{"rounds": True}, {"scale": float("nan")}, {"quality": 101}, {"mode": "bad"}, {"rounds": 0}]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_config(settings)

    def test_bad_image_rejected(self):
        with self.assertRaises(ValueError):
            decode_image(b"not an image")

    def test_transparency_is_explicit(self):
        file = io.BytesIO()
        Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(file, format="PNG")
        image, info = decode_image(file.getvalue())
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertTrue(info["normalization_notes"])

    def test_scores_flip_using_strict_threshold(self):
        class TestOnlyDetector:
            name, status, reason, available = "UNIT TEST STUB", "test", "", True
            def __init__(self):
                self.scores = iter([.5, .8, .4, .7])
            def detect(self, path):
                return {"score": next(self.scores)}
        report = self.run_analysis(detector=TestOnlyDetector())
        self.assertEqual(report["summary"]["flip_count"], 2)
        self.assertTrue(report["summary"]["regional_scan_recommended"])

    def test_failed_inference_remains_missing(self):
        class BrokenDetector:
            name, status, reason, available = "UNIT TEST STUB", "test", "", True
            def detect(self, path):
                raise RuntimeError("test failure")
        report = self.run_analysis(detector=BrokenDetector())
        self.assertEqual(report["detector"]["status"], "error")
        self.assertTrue(all(v["score"] is None and v["error"] for v in report["variants"]))

    def test_exports_preserve_dimensions_and_scores(self):
        report = self.run_analysis()
        loaded = json.loads((self.output / report["run_id"] / "report.json").read_text())
        self.assertEqual(report, loaded)
        self.assertTrue((self.output / report["run_id"] / "measurements.csv").is_file())


if __name__ == "__main__":
    unittest.main()
