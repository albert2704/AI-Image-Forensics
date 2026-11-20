"""Benchmark tests use synthetic pixels and explicitly fake detector fixtures."""
import copy
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from forensics import frequency_baseline, pipeline
from forensics.benchmark import (
    DEFAULT_CONDITIONS, _fingerprint_difference, canonical_image_hash, detector_fingerprint, freeze_protocol,
    grouped_paired_interval, load_protocol, render_condition, run_benchmark,
    summarize_benchmark, train_frequency_baseline,
)


class FixtureDetector:
    name, available, status, reason = "UNIT TEST DETECTOR", True, "test", ""
    fingerprint = {"model_type": "test", "checkpoint_sha256": "a" * 64, "preprocess_sha256": "b" * 64}

    def __init__(self, fail=False, invalid=False):
        self.calls = 0
        self.fail, self.invalid = fail, invalid

    def detect(self, path):
        self.calls += 1
        if self.fail:
            raise RuntimeError("intentional fixture failure")
        with Image.open(path) as image:
            score = float(np.asarray(image).mean() / 255)
        return {"score": float("nan") if self.invalid else score, "raw_logit": 0.0, "fixture_only": True}


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.csv"
        self.rows = []
        for split_index, split in enumerate(("train", "validation", "test")):
            for group in range(2):
                for label in (0, 1):
                    index = split_index * 4 + group * 2 + label
                    path = self.root / f"image-{index}.png"
                    rng = np.random.default_rng(index + 123)
                    pixels = rng.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
                    Image.fromarray(pixels).save(path)
                    self.rows.append({"source_id": f"source-{index:02d}", "path": path.name,
                                      "label": str(label), "generator": "real" if label == 0 else "fixture_generator",
                                      "group_id": f"{split}-group-{group}", "split": split,
                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source_url": "fixture:unit-test"})
        self.write_manifest()
        self.run_dir = self.root / "run"

    def write_manifest(self):
        with self.manifest.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def freeze(self, conditions=None):
        config = {"bfree_fingerprint": detector_fingerprint(FixtureDetector()), "bootstrap_samples": 40}
        if conditions is not None:
            config["conditions"] = conditions
        result = freeze_protocol(self.manifest, self.run_dir, config)
        return self.run_dir / "protocol.json", result

    def test_freeze_records_exact_data_code_groups_and_conditions(self):
        path, protocol = self.freeze()
        self.assertEqual(len(protocol["sources"]), 12)
        self.assertEqual(len(protocol["conditions"]), 9)
        self.assertEqual(len({row["group_id"] for row in protocol["sources"]}), 6)
        self.assertEqual(protocol["frequency"]["fit_split"], "train")
        self.assertEqual(load_protocol(path, verify_sources=True), protocol)
        self.assertFalse((self.run_dir / "results").exists())
        with self.assertRaises(FileExistsError):
            self.freeze()

    def test_source_group_leakage_and_duplicate_pixels_rejected(self):
        self.rows[4]["group_id"] = self.rows[0]["group_id"]
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "crosses"):
            self.freeze()
        self.rows[4]["group_id"] = "validation-group-0"
        self.rows[4]["path"] = self.rows[0]["path"]
        self.rows[4]["sha256"] = self.rows[0]["sha256"]
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Duplicate normalized"):
            self.freeze()

    def test_changed_protocol_manifest_or_source_blocks_before_scoring(self):
        path, _ = self.freeze()
        source = self.root / self.rows[0]["path"]
        original = source.read_bytes()
        source.write_bytes(original + b"source changed")
        detector = FixtureDetector()
        with self.assertRaisesRegex(ValueError, "Source changed"):
            run_benchmark(path, detector)
        self.assertEqual(detector.calls, 0)
        source.write_bytes(original)
        manifest_bytes = self.manifest.read_bytes()
        self.manifest.write_bytes(manifest_bytes + b"\n")
        with self.assertRaisesRegex(ValueError, "Manifest changed"):
            load_protocol(path)
        self.manifest.write_bytes(manifest_bytes)
        protocol = json.loads(path.read_text())
        protocol["threshold"] = .7
        path.write_text(json.dumps(protocol))
        with self.assertRaisesRegex(ValueError, "altered"):
            load_protocol(path)

    def test_render_matches_pipeline_history_and_matched_size_controls(self):
        image, _ = pipeline.decode_image((self.root / self.rows[0]["path"]).read_bytes())
        cumulative = next(item for item in DEFAULT_CONDITIONS if item["name"] == "combined_q95_s0.9_r3")
        control = next(item for item in DEFAULT_CONDITIONS if item["name"] == "independent_q95_s0.9_r3")
        current, content, fmt, history = render_condition(image, cumulative)
        independent, _, _, independent_history = render_condition(image, control)
        self.assertEqual(current.size, independent.size)
        self.assertEqual(current.size, (round(64 * .9 ** 3), round(48 * .9 ** 3)))
        self.assertEqual(len(history), 6)
        self.assertEqual(len(independent_history), 2)
        manual = image
        for index in range(1, 4):
            manual, expected, _, _ = pipeline.transform(manual, (round(64 * .9 ** index), round(48 * .9 ** index)), cumulative)
        self.assertEqual(content, expected)
        self.assertEqual(fmt, "JPEG")
        self.assertEqual(canonical_image_hash(current), canonical_image_hash(manual))
        self.assertNotEqual(canonical_image_hash(current), canonical_image_hash(independent))
        reverse = next(item for item in DEFAULT_CONDITIONS if item["name"] == "reverse_q95_s0.9_r3")
        self.assertEqual(render_condition(image, reverse)[2], "PNG")

    def test_budget_resume_is_append_only_and_never_duplicates_pairs(self):
        path, _ = self.freeze()
        detector = FixtureDetector()
        first = run_benchmark(path, detector, max_new_scores=2)
        journal = self.run_dir / "results" / "bfree" / "predictions.jsonl"
        prefix = journal.read_bytes()
        self.assertEqual(first["new_model_calls"], 2)
        self.assertTrue(first["budget_exhausted"])
        self.assertFalse(first["complete_requested_splits"])
        second = run_benchmark(path, detector)
        self.assertTrue(second["complete_requested_splits"])
        self.assertTrue(journal.read_bytes().startswith(prefix))
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual(len(rows), 36)
        self.assertEqual(len({(row["source_id"], row["condition"]) for row in rows}), 36)
        calls = detector.calls
        third = run_benchmark(path, detector)
        self.assertEqual(third["new_predictions"], 0)
        self.assertEqual(detector.calls, calls)
        self.assertTrue(all(row["split"] == "test" for row in rows))

    def test_canonical_cache_reuses_identical_condition_pixels(self):
        conditions = [copy.deepcopy(DEFAULT_CONDITIONS[0])]
        for index in (1, 3):
            conditions.append({"name": f"control-{index}", "operation": "jpeg", "quality": 85, "scale": 1,
                               "rounds": index, "mode": "independent", "order": "resize-jpeg"})
        path, _ = self.freeze(conditions)
        detector = FixtureDetector()
        result = run_benchmark(path, detector)
        self.assertEqual(result["new_predictions"], 12)
        self.assertEqual(result["cache_hits"], 4)
        self.assertEqual(detector.calls, 8)

    def test_failures_are_separate_and_retries_preserve_history(self):
        path, _ = self.freeze([DEFAULT_CONDITIONS[0]])
        detector = FixtureDetector(fail=True)
        result = run_benchmark(path, detector)
        self.assertEqual(result["new_failures"], 4)
        self.assertEqual(result["new_predictions"], 0)
        failure_path = self.run_dir / "results" / "bfree" / "failures.jsonl"
        original = failure_path.read_bytes()
        detector.fail = False
        skipped = run_benchmark(path, detector)
        self.assertEqual(skipped["new_model_calls"], 0)
        recovered = run_benchmark(path, detector, retry_failures=True)
        self.assertTrue(recovered["complete_requested_splits"])
        self.assertEqual(failure_path.read_bytes(), original)

    def test_invalid_score_is_not_a_prediction_and_wrong_model_cannot_resume(self):
        path, _ = self.freeze([DEFAULT_CONDITIONS[0]])
        result = run_benchmark(path, FixtureDetector(invalid=True), max_new_scores=1)
        self.assertEqual(result["new_predictions"], 0)
        self.assertEqual(result["new_failures"], 1)
        changed = FixtureDetector()
        changed.fingerprint = {**changed.fingerprint, "checkpoint_sha256": "c" * 64}
        with self.assertRaisesRegex(ValueError, "fingerprint differs"):
            run_benchmark(path, changed)
        self.assertEqual(changed.calls, 0)

    def test_preprocess_only_drift_names_the_key_and_both_values(self):
        path, _ = self.freeze([DEFAULT_CONDITIONS[0]])
        changed = FixtureDetector()
        changed.fingerprint = {**changed.fingerprint, "preprocess_sha256": "c" * 64}
        with self.assertRaises(ValueError) as caught:
            run_benchmark(path, changed)
        message = str(caught.exception)
        self.assertTrue(message.startswith("B-Free fingerprint differs from the frozen protocol"))
        self.assertIn("preprocess_sha256", message)
        self.assertIn("b" * 12, message)
        self.assertIn("c" * 12, message)
        self.assertNotIn("b" * 13, message)
        self.assertIn("checkpoint config", message)
        self.assertIn("adapter source", message)
        self.assertNotIn("\n", message)

    def test_checkpoint_drift_names_the_key_without_the_preprocess_clause(self):
        path, _ = self.freeze([DEFAULT_CONDITIONS[0]])
        changed = FixtureDetector()
        changed.fingerprint = {**changed.fingerprint, "checkpoint_sha256": "c" * 64}
        with self.assertRaises(ValueError) as caught:
            run_benchmark(path, changed)
        message = str(caught.exception)
        self.assertIn("checkpoint_sha256", message)
        self.assertIn("a" * 12, message)
        self.assertIn("c" * 12, message)
        self.assertNotIn("preprocess_sha256", message)
        self.assertNotIn("adapter source", message)

    def test_frequency_training_and_test_evaluation_keep_split_separation(self):
        path, protocol = self.freeze([DEFAULT_CONDITIONS[0]])
        with patch.object(frequency_baseline, "fit_model", wraps=frequency_baseline.fit_model) as fit:
            model_path = train_frequency_baseline(path)
            self.assertEqual(fit.call_count, 1)
            self.assertEqual(fit.call_args.args[2], [row["source_id"] for row in protocol["sources"] if row["split"] == "train"])
        self.assertEqual(train_frequency_baseline(path), model_path)
        detector = frequency_baseline.FrequencyDetector(model_path)
        result = run_benchmark(path, detector, detector_id="frequency")
        self.assertTrue(result["complete_requested_splits"])
        summary = summarize_benchmark(path, "frequency")
        self.assertEqual(summary["splits"]["train"]["counts"]["rows"], 0)
        self.assertEqual(summary["splits"]["test"]["counts"]["rows"], 4)


class FingerprintDifferenceTests(unittest.TestCase):
    def test_nested_versions_and_one_sided_keys_are_named(self):
        expected = {"model_type": "bfree", "device": "mps",
                    "versions": {"torch": "2.5.1", "timm": "1.0.12"}}
        actual = {"model_type": "bfree", "name": "B-Free",
                  "versions": {"torch": "2.6.0", "timm": "1.0.12", "PyYAML": "6.0.3"}}
        message = _fingerprint_difference(expected, actual)
        self.assertIn("versions.torch expected \"2.5.1\" actual \"2.6.0\"", message)
        self.assertIn("versions.PyYAML", message)
        self.assertIn("device", message)
        self.assertIn("name", message)
        self.assertNotIn("versions.timm", message)
        self.assertNotIn("\n", message)

    def test_a_missing_frozen_fingerprint_still_names_the_live_fields(self):
        actual = {"model_type": "bfree", "checkpoint_sha256": "a" * 64, "preprocess_sha256": "b" * 64}
        message = _fingerprint_difference(None, actual)
        self.assertIn("checkpoint_sha256", message)
        self.assertIn("preprocess_sha256", message)
        self.assertIn("<absent>", message)


class GroupBootstrapTests(unittest.TestCase):
    def test_cluster_bootstrap_keeps_related_real_fake_sources_together(self):
        rows = []
        # In each group, one class improves and the other worsens. Their paired
        # group contribution is exactly zero; independent-source resampling is not.
        for group in range(4):
            for label in (0, 1):
                source = f"{group}-{label}"
                before = .8 if label == 0 else .8
                after = .2 if label == 0 else .2
                for condition, score in (("baseline", before), ("jpeg", after)):
                    rows.append({"source_id": source, "label": label, "group_id": str(group), "condition": condition, "score": score})
        result = grouped_paired_interval(rows, "jpeg", samples=100)
        self.assertEqual(result["paired_groups"], 4)
        self.assertEqual(result["paired_sources"], 8)
        self.assertEqual(result["ci95"], [0.0, 0.0])
        self.assertEqual(result["valid_samples"], 100)

    def test_missing_pairs_and_disabled_intervals_are_explicit(self):
        result = grouped_paired_interval([], "jpeg", samples=100)
        self.assertIsNone(result["ci95"])
        self.assertIn("two paired groups", result["reason"])
        rows = [{"source_id": f"{group}-{label}", "label": label, "group_id": str(group), "condition": condition, "score": .4}
                for group in range(2) for label in (0, 1) for condition in ("baseline", "jpeg")]
        result = grouped_paired_interval(rows, "jpeg", samples=0)
        self.assertIsNone(result["ci95"])
        self.assertEqual(result["reason"], "Bootstrap disabled.")


if __name__ == "__main__":
    unittest.main()
