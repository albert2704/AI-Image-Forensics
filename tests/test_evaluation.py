"""Scientific metric checks use deliberately synthetic scores, not study results."""

import csv
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forensics.evaluation import evaluate_rows


def make_rows(scores=(0.1, 0.4, 0.35, 0.8), labels=(0, 0, 1, 1), condition="baseline"):
    return [
        {"source_id": f"source_{index}", "label": label,
         "generator": "real" if label == 0 else "fixture_generator",
         "condition": condition, "score": score}
        for index, (score, label) in enumerate(zip(scores, labels))
    ]


class MetricTests(unittest.TestCase):
    def test_known_binary_metrics(self):
        condition = evaluate_rows(make_rows())["conditions"]["baseline"]
        metrics = condition["metrics"]
        self.assertEqual(condition["counts"]["sources"], 4)
        self.assertEqual(condition["confusion"], {"tn": 2, "fp": 0, "fn": 1, "tp": 1})
        self.assertAlmostEqual(metrics["auroc"], 0.75)
        self.assertAlmostEqual(metrics["average_precision"], 5 / 6)
        self.assertAlmostEqual(metrics["balanced_accuracy"], 0.75)
        self.assertAlmostEqual(metrics["tpr"], 0.5)
        self.assertEqual(metrics["fpr"], 0.0)
        self.assertAlmostEqual(metrics["brier"], 0.158125)
        self.assertAlmostEqual(metrics["nll"], -math.log(0.9 * 0.6 * 0.35 * 0.8) / 4)
        self.assertAlmostEqual(metrics["ece"], 0.3375)

    def test_ties_are_grouped_and_order_invariant(self):
        rows = make_rows(scores=(0.5, 0.5, 0.5, 0.5))
        report = evaluate_rows(rows)
        metrics = report["conditions"]["baseline"]["metrics"]
        self.assertEqual(metrics["auroc"], 0.5)
        self.assertEqual(metrics["average_precision"], 0.5)
        self.assertEqual(metrics["ece"], 0)
        self.assertEqual(report, evaluate_rows(list(reversed(rows))))

    def test_partial_ties_average_precision_uses_complete_score_groups(self):
        metrics = evaluate_rows(make_rows(scores=(0.7, 0.2, 0.7, 0.9)))["conditions"]["baseline"]["metrics"]
        self.assertAlmostEqual(metrics["auroc"], 0.875)
        self.assertAlmostEqual(metrics["average_precision"], 5 / 6)

    def test_missing_classes_produce_null_metrics_with_reasons(self):
        for label in (0, 1):
            condition = evaluate_rows(make_rows(scores=(0.2, 0.8), labels=(label, label)))["conditions"]["baseline"]
            for metric in ("auroc", "average_precision", "balanced_accuracy"):
                self.assertIsNone(condition["metrics"][metric])
                self.assertIn(metric, condition["metric_reasons"])
            self.assertIsNotNone(condition["metrics"]["brier"])
            self.assertIsNone(condition["metrics"]["tpr" if label == 0 else "fpr"])

    def test_ece_boundary_membership_and_empty_bins(self):
        condition = evaluate_rows(make_rows(scores=(0, 0.3, 0.9, 1)))["conditions"]["baseline"]
        bins = condition["ece_bins"]
        self.assertEqual([entry["count"] for entry in bins], [1, 0, 0, 1, 0, 0, 0, 0, 0, 2])
        self.assertIsNone(bins[1]["mean_score"])
        self.assertTrue(bins[-1]["upper_inclusive"])
        self.assertFalse(bins[3]["upper_inclusive"])
        self.assertEqual(sum(entry["count"] for entry in bins), 4)
        self.assertAlmostEqual(condition["metrics"]["ece"], 0.1)

    def test_endpoints_have_finite_nll_and_no_nonstandard_json(self):
        report = evaluate_rows(make_rows(scores=(1, 1, 0, 0)))
        nll = report["conditions"]["baseline"]["metrics"]["nll"]
        self.assertTrue(math.isfinite(nll))
        self.assertGreater(nll, 30)
        json.dumps(report, allow_nan=False)

    def test_threshold_is_strict_and_does_not_change_ranking_metrics(self):
        rows = make_rows(scores=(0.1, 0.4, 0.5, 0.8))
        first = evaluate_rows(rows, threshold=0.5)["conditions"]["baseline"]
        second = evaluate_rows(rows, threshold=0.8)["conditions"]["baseline"]
        self.assertEqual(first["confusion"]["tp"], 1)
        self.assertEqual(second["confusion"]["tp"], 0)
        self.assertEqual(first["metrics"]["auroc"], second["metrics"]["auroc"])
        self.assertEqual(first["metrics"]["brier"], second["metrics"]["brier"])


class PairingTests(unittest.TestCase):
    def test_paired_deltas_and_source_bootstrap(self):
        rows = make_rows() + make_rows(scores=(0.7, 0.2, 0.1, 0.9), condition="jpeg_r1")
        report = evaluate_rows(rows, bootstrap_samples=1000, seed=2026)
        pair = report["paired_vs_baseline"]["jpeg_r1"]
        self.assertEqual(report["counts"]["independent_sources"], 4)
        self.assertEqual(pair["counts"]["paired_sources"], 4)
        self.assertAlmostEqual(pair["score_delta"]["mean"], 0.0625)
        self.assertEqual(pair["label_flip_rate"], 0.25)
        self.assertEqual(pair["flips"], {"negative_to_positive": 1, "positive_to_negative": 0})
        self.assertEqual(pair["balanced_accuracy_delta"], -0.25)
        self.assertEqual(pair["balanced_accuracy_delta_ci95"], [-0.5, 0.0])
        self.assertEqual(pair["bootstrap"]["valid_samples"], 1000)
        self.assertEqual(report, evaluate_rows(list(reversed(rows)), bootstrap_samples=1000, seed=2026))

    def test_identical_predictions_have_exact_zero_paired_interval(self):
        pair = evaluate_rows(make_rows() + make_rows(condition="resize_r1"), bootstrap_samples=20)["paired_vs_baseline"]["resize_r1"]
        self.assertEqual(pair["balanced_accuracy_delta_ci95"], [0.0, 0.0])
        self.assertEqual(pair["label_flip_rate"], 0.0)
        self.assertEqual(pair["score_delta"]["mean"], 0.0)

    def test_missing_variants_are_counted_and_pair_metrics_use_intersection(self):
        variant = make_rows(scores=(0.7, 0.2, 0.1, 0.9), condition="jpeg_r1")[1:]
        variant.append({"source_id": "new_source", "label": 0, "generator": "real", "condition": "jpeg_r1", "score": 0.99})
        pair = evaluate_rows(make_rows() + variant)["paired_vs_baseline"]["jpeg_r1"]
        self.assertEqual(pair["counts"]["paired_sources"], 3)
        self.assertEqual(pair["counts"]["condition_sources_without_baseline"], 1)
        self.assertEqual(pair["counts"]["baseline_sources_without_condition"], 1)
        self.assertEqual(pair["balanced_accuracy_delta"], 0.0)
        self.assertEqual(pair["label_flip_rate"], 0.0)
        self.assertIsNone(pair["balanced_accuracy_delta_ci95"])
        self.assertIn("At least two", pair["reason"])

    def test_no_baseline_is_explicit(self):
        report = evaluate_rows(make_rows(condition="jpeg_r1"))
        pair = report["paired_vs_baseline"]["jpeg_r1"]
        self.assertEqual(pair["counts"]["paired_sources"], 0)
        self.assertIsNone(pair["label_flip_rate"])
        self.assertIsNone(pair["balanced_accuracy_delta"])
        self.assertIsNotNone(pair["reason"])
        self.assertTrue(report["warnings"])

    def test_one_paired_class_retains_score_delta_but_not_bacc(self):
        rows = make_rows(scores=(0.1, 0.8), labels=(1, 1))
        rows += make_rows(scores=(0.7, 0.9), labels=(1, 1), condition="jpeg_r1")
        pair = evaluate_rows(rows)["paired_vs_baseline"]["jpeg_r1"]
        self.assertAlmostEqual(pair["score_delta"]["mean"], 0.35)
        self.assertIsNone(pair["score_delta"]["mean_negative"])
        self.assertIsNone(pair["balanced_accuracy_delta"])
        self.assertIn("both label classes", pair["reason"])

    def test_bootstrap_can_be_disabled_without_losing_point_estimate(self):
        pair = evaluate_rows(make_rows() + make_rows(condition="jpeg_r1"), bootstrap_samples=0)["paired_vs_baseline"]["jpeg_r1"]
        self.assertEqual(pair["balanced_accuracy_delta"], 0.0)
        self.assertIsNone(pair["balanced_accuracy_delta_ci95"])
        self.assertEqual(pair["bootstrap"]["valid_samples"], 0)
        self.assertIn("disabled", pair["reason"])


class ValidationAndCLITests(unittest.TestCase):
    def test_duplicate_variant_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            evaluate_rows(make_rows() + make_rows())

    def test_inconsistent_source_label_or_generator_rejected(self):
        for key, value in (("label", 1), ("generator", "different_generator")):
            rows = make_rows() + make_rows(condition="jpeg_r1")
            rows[-4][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "inconsistent"):
                evaluate_rows(rows)

    def test_invalid_scores_labels_and_metadata_rejected(self):
        cases = [("score", value) for value in (float("nan"), float("inf"), -0.01, 1.01, None, True)]
        cases += [("label", value) for value in (2, "AI", None, True)]
        cases += [("source_id", ""), ("generator", None), ("condition", " ")]
        for key, value in cases:
            rows = make_rows()
            rows[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                evaluate_rows(rows)
        with self.assertRaisesRegex(ValueError, "missing"):
            evaluate_rows([{"source_id": "one"}])

    def test_invalid_parameters_rejected(self):
        cases = [{"threshold": float("nan")}, {"threshold": -1}, {"threshold": True},
                 {"bootstrap_samples": -1}, {"bootstrap_samples": 1.5}, {"bootstrap_samples": True},
                 {"seed": -1}, {"seed": 0.5}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                evaluate_rows(make_rows(), **kwargs)

    def test_empty_input_is_not_fabricated_data(self):
        report = evaluate_rows([])
        self.assertEqual(report["conditions"], {})
        self.assertEqual(report["counts"]["independent_sources"], 0)
        self.assertTrue(report["warnings"])

    def test_csv_cli_roundtrip_and_invalid_header(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "predictions.csv"
            json_path = Path(directory) / "nested" / "metrics.json"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=("source_id", "label", "generator", "condition", "score"))
                writer.writeheader()
                writer.writerows(make_rows())
            process = subprocess.run(
                [sys.executable, "-m", "forensics.evaluation", str(csv_path), "-o", str(json_path), "--bootstrap-samples", "20"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(json_path.read_text())["conditions"]["baseline"]["metrics"]["auroc"], 0.75)
            csv_path.write_text("wrong,columns\na,b\n", encoding="utf-8")
            process = subprocess.run([sys.executable, "-m", "forensics.evaluation", str(csv_path)], capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 2)
            self.assertIn("CSV is missing columns", process.stderr)


if __name__ == "__main__":
    unittest.main()
