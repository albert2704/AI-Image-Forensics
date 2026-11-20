import re
import unittest
from pathlib import Path

from forensics.pipeline import summarize

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
TRANSLATED = set(re.findall(r'^\s{4}"([^"]+)":', APP, re.M))
DYNAMIC = "derivatives cross the configured"


def variants(score, derivative):
    return [{"id": "original", "round": 0, "width": 512, "height": 512, "score": score, "error": None},
            {"id": "v1", "round": 1, "width": 512, "height": 512, "score": derivative, "error": None}]


def summary(score, derivative, mode="cumulative"):
    return summarize(variants(score, derivative), {"mode": mode, "threshold": .5}, {}, [])


class TranslationTests(unittest.TestCase):
    def test_every_summary_title_and_warning_has_a_translation(self):
        cases = [summary(.2, .8), summary(.9, .8), summary(.1, .12), summary(.2, .8, mode="independent"), summary(.2, None)]
        for case in cases:
            self.assertTrue(case["title"] in TRANSLATED, case["title"])
            for warning in case["warnings"]:
                self.assertTrue(warning in TRANSLATED, warning)
            if DYNAMIC in case["text"]:
                self.assertEqual(case["text"].count(DYNAMIC), 1)
            else:
                self.assertTrue(case["text"] in TRANSLATED, case["text"])

    def test_dynamic_flip_sentence_has_a_translation_rule(self):
        self.assertTrue(DYNAMIC in APP)

    def test_small_image_warning_has_a_translation(self):
        case = summarize([{"id": "original", "round": 0, "width": 100, "height": 100, "score": .2, "error": None},
                          {"id": "v1", "round": 1, "width": 100, "height": 100, "score": .8, "error": None}],
                         {"mode": "cumulative", "threshold": .5}, {}, [])
        warning = next(item for item in case["warnings"] if "below 224 px" in item)
        self.assertTrue(warning in TRANSLATED)


if __name__ == "__main__":
    unittest.main()
