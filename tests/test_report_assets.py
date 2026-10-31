import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("report_assets", ROOT / "scripts" / "report_assets.py")
report_assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report_assets)


class ReportAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "output" / "figures").mkdir(parents=True)
        (self.root / "output" / "figures" / "plot.png").write_bytes(b"png")

    def test_repo_file_stays_relative(self):
        relative = report_assets.repo_relative(self.root / "output" / "figures" / "plot.png", self.root)
        self.assertEqual(relative, Path("output/figures/plot.png"))

    def test_foreign_absolute_path_is_salvaged_from_a_marker(self):
        path = "/Users/albert/Work Space/XLA/AI Image Forensics/output/figures/plot.png"
        relative = report_assets.repo_relative(path, self.root)
        self.assertEqual(relative, Path("output/figures/plot.png"))

    def test_path_that_does_not_exist_in_the_repo_is_dropped(self):
        self.assertIsNone(report_assets.repo_relative(self.root / "output" / "figures" / "missing.png", self.root))
        self.assertIsNone(report_assets.repo_relative("/etc/hosts", self.root))

    def test_symlink_target_outside_the_repo_is_dropped(self):
        outside = Path(self.temp.name).parent / "outside-secret.png"
        outside.write_bytes(b"x")
        self.addCleanup(outside.unlink)
        (self.root / "output" / "alias.png").symlink_to(outside)

        self.assertIsNone(report_assets.repo_relative(self.root / "output" / "alias.png", self.root))
        line = report_assets.markdown_image("Source", self.root / "output" / "alias.png", self.root)
        self.assertIn("not in this repository", line)

    def test_traversal_tail_is_dropped(self):
        outside = Path(self.temp.name).parent / "outside-secret.png"
        outside.write_bytes(b"x")
        self.addCleanup(outside.unlink)
        for path in (f"{self.root}/output/../../outside-secret.png",
                     "/Users/albert/Work Space/XLA/AI Image Forensics/output/../../outside-secret.png"):
            with self.subTest(path=path):
                self.assertIsNone(report_assets.repo_relative(path, self.root))

    def test_markdown_never_emits_an_absolute_path(self):
        path = "/Users/albert/Work Space/XLA/AI Image Forensics/output/figures/plot.png"
        line = report_assets.markdown_image("Measured figure", path, self.root)
        self.assertEqual(line, "![Measured figure](../output/figures/plot.png)\n")
        absent = report_assets.markdown_image("Source", "/Users/albert/Work Space/external/x.png", self.root)
        self.assertNotIn("/Users/", absent)
        self.assertIn("not in this repository", absent)


if __name__ == "__main__":
    unittest.main()
