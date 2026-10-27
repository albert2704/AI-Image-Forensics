"""Study 2 tests use synthetic pixels and an explicitly fake detector fixture."""
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from forensics import breakpoint
from forensics.benchmark import DEFAULT_CONDITIONS, _validate_conditions, freeze_protocol, render_condition, run_benchmark


class FixtureDetector:
    name, available, status, reason = "UNIT TEST DETECTOR", True, "test", ""
    fingerprint = {"model_type": "test", "checkpoint_sha256": "a" * 64, "preprocess_sha256": "b" * 64}

    def detect(self, path):
        with Image.open(path) as image:
            return {"score": float(np.asarray(image).mean() / 255), "raw_logit": 0.0, "fixture_only": True}


class BreakpointGridTests(unittest.TestCase):
    def test_grid_is_complete_unique_and_valid(self):
        conditions = breakpoint.grid_conditions()
        names = [condition["name"] for condition in conditions]
        self.assertEqual(len(names), len(breakpoint.GRID_SCALES) * len(breakpoint.GRID_QUALITIES))
        self.assertEqual(len(set(names)), len(names))
        self.assertIn("baseline", names)
        self.assertIn(breakpoint.PRIMARY_CONDITION, names)
        self.assertEqual(len(_validate_conditions(conditions)), len(conditions))

    def test_cells_are_single_pass_at_target_size(self):
        original = Image.fromarray(np.random.default_rng(1).integers(0, 256, (48, 64, 3), dtype=np.uint8))
        conditions = {condition["name"]: condition for condition in breakpoint.grid_conditions()}
        image, _, fmt, history = render_condition(original, conditions["s0.50_q50"])
        self.assertEqual((image.size, fmt), ((32, 24), "JPEG"))
        self.assertEqual([step["type"] for step in history], ["resize", "jpeg"])
        image, _, fmt, history = render_condition(original, conditions["s0.70_png"])
        self.assertEqual((image.size, fmt, len(history)), ((45, 34), "PNG", 1))
        image, _, fmt, history = render_condition(original, conditions["s1.00_q85"])
        self.assertEqual((image.size, fmt, [step["type"] for step in history]), ((64, 48), "JPEG", ["jpeg"]))


class BreakpointStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.manifest = root / "manifest.csv"
        rows = []
        for split_index, split in enumerate(("train", "validation", "test")):
            for group in range(2):
                for label in (0, 1):
                    index = split_index * 4 + group * 2 + label
                    path = root / f"image-{index}.png"
                    pixels = np.random.default_rng(index + 7).integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
                    Image.fromarray(pixels).save(path)
                    rows.append({"source_id": f"source-{index:02d}", "path": path.name, "label": str(label),
                                 "generator": "real" if label == 0 else "fixture_generator", "group_id": f"{split}-group-{group}",
                                 "split": split, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source_url": "fixture:unit-test"})
        with self.manifest.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.run_dir = root / "study2"

    def test_freeze_run_and_analyze(self):
        protocol = breakpoint.freeze(self.manifest, self.run_dir, FixtureDetector())
        self.assertEqual(protocol["study_name"], breakpoint.STUDY_NAME)
        path = self.run_dir / "protocol.json"
        result = run_benchmark(path, FixtureDetector(), ["test"])
        self.assertTrue(result["complete_requested_splits"])
        summary = breakpoint.analyze(path)
        self.assertTrue(summary["coverage"]["complete"])
        self.assertEqual(summary["coverage"]["complete_sources"], 4)
        self.assertEqual(len(summary["grid"]), len(protocol["conditions"]))
        self.assertEqual(summary["primary_contrast"]["condition"], breakpoint.PRIMARY_CONDITION)
        baseline = next(cell for cell in summary["grid"] if cell["condition"] == "baseline")
        self.assertEqual(baseline["decision_change_rate"], 0)
        with (self.run_dir / "analysis" / "bfree" / "breakpoints.csv").open() as stream:
            records = list(csv.DictReader(stream))
        self.assertEqual(len(records), 4)
        self.assertTrue((self.run_dir / "analysis" / "bfree" / "grid.csv").is_file())

    def test_partial_runs_report_missing_sources_instead_of_filling_them(self):
        breakpoint.freeze(self.manifest, self.run_dir, FixtureDetector())
        path = self.run_dir / "protocol.json"
        run_benchmark(path, FixtureDetector(), ["test"], max_new_scores=40)
        summary = breakpoint.analyze(path)
        self.assertFalse(summary["coverage"]["complete"])
        self.assertEqual(summary["coverage"]["complete_sources"], 1)
        self.assertEqual(summary["coverage"]["predictions"], 40)

    def test_refuses_a_protocol_without_the_grid(self):
        freeze_protocol(self.manifest, self.run_dir, {"conditions": DEFAULT_CONDITIONS,
                                                      "bfree_fingerprint": FixtureDetector.fingerprint})
        with self.assertRaises(ValueError):
            breakpoint.analyze(self.run_dir / "protocol.json")

    def test_unavailable_detector_cannot_freeze(self):
        class Unavailable:
            available, reason = False, "not configured"
        with self.assertRaises(ValueError):
            breakpoint.freeze(self.manifest, self.run_dir, Unavailable())


if __name__ == "__main__":
    unittest.main()
