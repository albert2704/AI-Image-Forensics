import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UiRulesTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_rules_match_the_presentation_contract(self):
        result = subprocess.run(["node", "tests/test_ui_rules.cjs"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ui rules ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
