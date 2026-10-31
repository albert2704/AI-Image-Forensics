"""Modal batch runner tests: schema rows, frozen recipes, token gate, fan-out."""
import copy
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from forensics import pipeline
from forensics.benchmark import DEFAULT_CONDITIONS, render_condition

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("modal_score", ROOT / "scripts" / "modal_score.py")
modal_score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(modal_score)


def write_png(path, size=(48, 40), seed=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size)
    image.putdata([((x * 7 + seed) % 256, (x * 3) % 256, (x * 11 + seed) % 256)
                   for x in range(size[0] * size[1])])
    image.save(path, format="PNG")
    return image


class ConditionRecipeTests(unittest.TestCase):
    def test_nine_names_map_to_the_delivered_protocol_recipes(self):
        protocol = json.loads((ROOT / "output" / "benchmark" / "protocol.json").read_text())
        recipes = modal_score.condition_recipes(protocol["conditions"])
        self.assertEqual(tuple(recipes), modal_score.CONDITION_ORDER)
        self.assertEqual(len(recipes), 9)
        self.assertEqual(recipes["baseline"]["rounds"], 0)
        self.assertEqual(recipes["jpeg_q85_r3"],
                         {"name": "jpeg_q85_r3", "operation": "jpeg", "quality": 85, "scale": 1.0,
                          "rounds": 3, "mode": "cumulative", "order": "resize-jpeg"})
        self.assertEqual(recipes["reverse_q95_s0.9_r3"]["order"], "jpeg-resize")
        self.assertEqual(recipes["independent_q95_s0.9_r3"]["mode"], "independent")
        self.assertEqual(recipes, modal_score.FROZEN_RECIPES)

    def test_changed_incomplete_or_duplicate_sets_are_refused(self):
        changed = copy.deepcopy(DEFAULT_CONDITIONS)
        changed[1]["quality"] = 90
        with self.assertRaises(ValueError):
            modal_score.condition_recipes(changed)
        with self.assertRaises(ValueError):
            modal_score.condition_recipes(DEFAULT_CONDITIONS[:-1])
        with self.assertRaises(ValueError):
            modal_score.condition_recipes([*DEFAULT_CONDITIONS, DEFAULT_CONDITIONS[0]])


class PredictionRowTests(unittest.TestCase):
    def task(self, **overrides):
        task = {"source_id": "raise:real:abc", "label": 0, "generator": "real",
                "group_id": "raise1k:abc", "split": "test", "condition": "jpeg_q85_r3",
                "path": "images/real/abc.png", "sha256": "0" * 64, "recipe": {}}
        task.update(overrides)
        return task

    def test_row_is_exactly_the_frozen_eight_columns(self):
        row = modal_score.prediction_row(self.task(), {"score": .0234393974890692, "raw_logit": -3.729618549346924})
        self.assertEqual(tuple(row), modal_score.COLUMNS)
        self.assertEqual(row, {"source_id": "raise:real:abc", "label": 0, "generator": "real",
                               "group_id": "raise1k:abc", "split": "test", "condition": "jpeg_q85_r3",
                               "score": .0234393974890692, "raw_logit": -3.729618549346924})

    def test_missing_logit_stays_blank_and_rows_sort_like_the_frozen_csv(self):
        rows = [
            modal_score.prediction_row(self.task(source_id="b", condition="baseline"), {"score": .5, "raw_logit": 0.0}),
            modal_score.prediction_row(self.task(source_id="a", condition="jpeg_q85_r3"), {"score": .25}),
            modal_score.prediction_row(self.task(source_id="a", condition="baseline"), {"score": .75, "raw_logit": 1.1}),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = modal_score.write_predictions(rows, Path(temporary) / "nested" / "predictions.csv")
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                written = list(reader)
                self.assertEqual(reader.fieldnames, list(modal_score.COLUMNS))
        self.assertEqual([(row["source_id"], row["condition"]) for row in written],
                         [("a", "baseline"), ("a", "jpeg_q85_r3"), ("b", "baseline")])
        self.assertEqual(float(written[2]["raw_logit"]), 0.0)
        self.assertEqual(written[1]["raw_logit"], "")

    def test_non_finite_bool_or_out_of_range_scores_are_refused(self):
        for prediction in ({"score": 1.2}, {"score": -.1}, {"score": float("nan")},
                           {"score": True}, {"score": 0.5, "raw_logit": float("inf")}, {}):
            with self.subTest(prediction=prediction), self.assertRaises(ValueError):
                modal_score.prediction_row(self.task(), prediction)


class TokenGateTests(unittest.TestCase):
    def test_missing_token_names_the_setup_command(self):
        with self.assertRaises(modal_score.MissingTokenError) as caught:
            modal_score.require_modal_token({})
        self.assertIn("MODAL_TOKEN_ID", str(caught.exception))
        self.assertIn("modal setup", str(caught.exception))
        with self.assertRaises(modal_score.MissingTokenError):
            modal_score.require_modal_token({"MODAL_TOKEN_ID": "id"})
        modal_score.require_modal_token({"MODAL_TOKEN_ID": "id", "MODAL_TOKEN_SECRET": "secret"})

    def test_cli_without_a_token_fails_before_importing_modal(self):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"}}
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "modal_score.py"), "--output",
                 str(Path(temporary) / "predictions.csv")],
                capture_output=True, text=True, env=environment, cwd=temporary, timeout=120,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("modal setup", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)


class SourceAndTaskTests(unittest.TestCase):
    def make_manifest(self, directory, rows):
        manifest = Path(directory) / "manifest.csv"
        fields = ["source_id", "path", "label", "generator", "group_id", "split", "sha256", "source_url"]
        with manifest.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return manifest

    def test_test_split_only_with_verified_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            entries = []
            for name, split in (("b", "test"), ("a", "test"), ("c", "train")):
                path = directory / "images" / f"{name}.png"
                write_png(path, seed=len(name))
                entries.append({"source_id": f"src:{name}", "path": f"images/{name}.png", "label": "1",
                                "generator": "dalle3", "group_id": f"group:{name}", "split": split,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source_url": "https://example"})
            manifest = self.make_manifest(directory, entries)
            sources = modal_score.test_sources(manifest, expected=None)
            self.assertEqual([source["source_id"] for source in sources], ["src:a", "src:b"])
            self.assertTrue(all(source["split"] == "test" for source in sources))
            with self.assertRaises(ValueError):
                modal_score.test_sources(manifest, expected=3)
            (directory / "images" / "a.png").write_bytes(b"not the delivered image")
            with self.assertRaises(ValueError):
                modal_score.test_sources(manifest, expected=None)

    def test_missing_image_is_named(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = self.make_manifest(directory, [{
                "source_id": "src:a", "path": "images/a.png", "label": "0", "generator": "real",
                "group_id": "group:a", "split": "test", "sha256": "0" * 64, "source_url": "https://example"}])
            with self.assertRaises(ValueError) as caught:
                modal_score.test_sources(manifest, expected=None)
            self.assertIn("missing", str(caught.exception).lower())

    def test_tasks_fan_out_one_per_condition_and_smoke_takes_the_first_source(self):
        recipes = modal_score.condition_recipes()
        sources = [{"source_id": f"src:{index}", "label": index % 2, "generator": "real",
                    "group_id": f"group:{index}", "split": "test", "path": f"images/{index}.png",
                    "sha256": "0" * 64} for index in range(2)]
        tasks = modal_score.build_tasks(sources, recipes)
        self.assertEqual(len(tasks), 18)
        self.assertEqual([task["condition"] for task in tasks[:9]], list(modal_score.CONDITION_ORDER))
        smoke = modal_score.build_tasks(sources, recipes, smoke=True)
        self.assertEqual(len(smoke), 9)
        self.assertEqual({task["source_id"] for task in smoke}, {"src:0"})


class ScoreTaskTests(unittest.TestCase):
    class FakeDetector:
        def __init__(self):
            self.seen = []
            self.prediction = {"score": .75, "raw_logit": 1.0986122886681098, "score_kind": "ai_generation",
                               "model": "B-Free", "model_revision": "c" * 40, "checkpoint_sha256": "d" * 64,
                               "device": "cuda", "runtime_seconds": .01, "calibrated_probability": False}

        def detect(self, path):
            with Image.open(path) as image:
                self.seen.append(image.convert("RGB").copy())
            return dict(self.prediction)

    def make_task(self, directory, condition="jpeg_q85_r3"):
        image = write_png(Path(directory) / "images" / "a.png", size=(120, 80))
        data = (Path(directory) / "images" / "a.png").read_bytes()
        return {"source_id": "src:a", "label": 1, "generator": "dalle3", "group_id": "group:a",
                "split": "test", "condition": condition, "path": "images/a.png",
                "sha256": hashlib.sha256(data).hexdigest(),
                "recipe": modal_score.condition_recipes()[condition]}, image

    def test_detector_receives_exactly_the_frozen_condition_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            task, _ = self.make_task(temporary)
            detector = self.FakeDetector()
            row, response = modal_score.score_task(task, detector, data_root=temporary)
            original, _ = pipeline.decode_image((Path(temporary) / "images" / "a.png").read_bytes())
            expected, _content, _fmt, _history = render_condition(original, task["recipe"])
        self.assertEqual(len(detector.seen), 1)
        self.assertEqual(detector.seen[0].size, expected.size)
        self.assertEqual(detector.seen[0].tobytes(), expected.tobytes())
        self.assertEqual(row["condition"], "jpeg_q85_r3")
        self.assertEqual(row["score"], .75)
        self.assertEqual(row["raw_logit"], 1.0986122886681098)
        self.assertEqual(response["checkpoint_sha256"], "d" * 64)

    def test_changed_source_bytes_fail_the_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            task, _ = self.make_task(temporary, condition="baseline")
            task["sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                modal_score.score_task(task, self.FakeDetector(), data_root=temporary)


if __name__ == "__main__":
    unittest.main()
