import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("report_assets", ROOT / "scripts" / "report_assets.py")
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)
WRITEUP = ROOT / "docs" / "RESEARCH_WRITEUP.md"


class GeneratedDocsTests(unittest.TestCase):
    def test_tracked_writeup_has_no_absolute_local_paths(self):
        self.assertNotIn("/Users/", WRITEUP.read_text(encoding="utf-8"))

    def test_regional_image_lines_match_the_generator(self):
        regional = json.loads((ROOT / "output/model-verification/trufor-small-reference-check.json").read_text())
        files = [ROOT / "external/TruFor/test_docker/images/tampered2.png",
                 Path(regional["heatmap_path"]), Path(regional["reliability_path"]), Path(regional["overlay_path"])]
        text = WRITEUP.read_text(encoding="utf-8")
        for label, path in zip(["Source", "Anomaly", "Reliability", "Overlay"], files):
            line = assets.markdown_image(label, path, ROOT).strip()
            with self.subTest(label=label):
                self.assertIn(line, text)


if __name__ == "__main__":
    unittest.main()
