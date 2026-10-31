import importlib.util
import json
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
