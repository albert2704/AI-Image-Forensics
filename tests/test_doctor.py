import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("doctor", ROOT / "scripts" / "doctor.py")
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


def status(rows, name):
    return next(row["status"] for row in rows if row["name"] == name)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_bare_checkout_reports_what_is_missing(self):
        rows = doctor.collect(self.root)
        self.assertEqual(status(rows, "images"), "missing")
        self.assertEqual(status(rows, "demo example"), "missing")
        self.assertEqual(status(rows, "planner"), "missing")
        rendered = doctor.render(rows)
        self.assertIn("blocks the recorded demo button", rendered)

    def test_present_pieces_are_reported_as_present(self):
        manifest = self.root / "data" / "benchmark" / "manifest.csv"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("source_id,path,label,generator\ns1,a.png,0,real\n")
        (manifest.parent / "a.png").write_bytes(b"png")
        run_id = "a" * 32
        (self.root / "output" / "model-verification" / run_id).mkdir(parents=True)
        (self.root / "output" / "verified-example.json").write_text(json.dumps({"run_id": run_id}))

        rows = doctor.collect(self.root)

        self.assertEqual(status(rows, "images"), "ok")
        self.assertEqual(status(rows, "demo example"), "ok")
        self.assertEqual(status(rows, "your runs"), "missing")

    def test_corrupt_pointer_is_reported_not_raised(self):
        output = self.root / "output"
        output.mkdir()
        pointer = output / "verified-example.json"
        for payload in ("{", "[]"):
            pointer.write_text(payload)
            with self.subTest(payload=payload):
                rows = doctor.collect(self.root)
                self.assertEqual(status(rows, "demo example"), "missing")

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_unreadable_runs_directory_is_reported(self):
        runs = self.root / "output" / "runs"
        runs.mkdir(parents=True)
        os.chmod(runs, 0)
        self.addCleanup(os.chmod, runs, 0o700)

        rows = doctor.collect(self.root)

        self.assertEqual(status(rows, "your runs"), "missing")
        self.assertIn("cannot read output/runs", next(row["detail"] for row in rows if row["name"] == "your runs"))

    def test_a_run_id_cannot_escape_the_output_tree(self):
        output = self.root / "output"
        output.mkdir()
        (output / "model-verification").mkdir()
        pointer = output / "verified-example.json"
        for run_id in ("../../..", "..", "", "a" * 32):
            pointer.write_text(json.dumps({"run_id": run_id}))
            with self.subTest(run_id=run_id):
                self.assertNotEqual(status(doctor.collect(self.root), "demo example"), "ok")

    @unittest.skipIf(os.geteuid() == 0, "root ignores file permissions")
    def test_unreadable_manifest_is_reported(self):
        manifest = self.root / "data" / "benchmark" / "manifest.csv"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("source_id,path,label,generator\n")
        os.chmod(manifest, 0)
        self.addCleanup(os.chmod, manifest, 0o600)

        rows = doctor.collect(self.root)

        self.assertEqual(status(rows, "images"), "missing")
        self.assertIn("cannot read", next(row["detail"] for row in rows if row["name"] == "images"))

    def test_partial_image_set_is_not_ok(self):
        manifest = self.root / "data" / "benchmark" / "manifest.csv"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("source_id,path,label,generator\ns1,a.png,0,real\ns2,b.png,1,dalle3\n")
        (manifest.parent / "a.png").write_bytes(b"png")

        rows = doctor.collect(self.root)

        self.assertEqual(status(rows, "images"), "partial")
        self.assertIn("1 of 2 manifest files", next(row["detail"] for row in rows if row["name"] == "images"))


if __name__ == "__main__":
    unittest.main()
