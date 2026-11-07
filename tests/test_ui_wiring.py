import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
PAGE = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


class UiWiringTests(unittest.TestCase):
    def test_page_loads_the_rules_module_before_the_app(self):
        self.assertLess(PAGE.index('/rules.js'), PAGE.index('/app.js'))

    def test_app_uses_the_extracted_rules(self):
        for call in ("rules.completionTag(", "rules.trajectoryTitle(", "rules.stopReasonText("):
            with self.subTest(call=call):
                self.assertIn(call, APP)

    def test_app_no_longer_claims_completion_unconditionally(self):
        self.assertFalse("HOÀN TẤT ${Math.max(0, variants.length - 1)}" in APP)
        self.assertFalse("reasons[summary.stop_reason]" in APP)


if __name__ == "__main__":
    unittest.main()
