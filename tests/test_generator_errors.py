"""Fixture tests for scripts/analyze_generator_errors.py."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forensics import evaluation
from forensics.benchmark import DEFAULT_CONDITIONS, freeze_protocol, load_protocol
from forensics.evaluation import evaluate_rows
from scripts.analyze_generator_errors import analyze_study


def _write_png(path: Path, seed: int) -> str:
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, size=(32, 32, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GeneratorErrorAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.csv"
        self.study = self.root / "study"

        manifest_rows = []
        idx = 0
        for split, group_specs in (
            ("train", [("g-train", "alpha")]),
            ("validation", [("g-val", "alpha")]),
            ("test", [("g-a1", "alpha"), ("g-a2", "alpha"), ("g-b1", "beta"), ("g-b2", "beta")]),
        ):
            for group_id, family in group_specs:
                for label in (0, 1):
                    idx += 1
                    img_path = self.root / f"img-{idx:02d}.png"
                    sha = _write_png(img_path, seed=1000 + idx)
                    manifest_rows.append({
                        "source_id": f"{split}-{group_id}-{label}",
                        "path": img_path.name,
                        "label": str(label),
                        "generator": "real" if label == 0 else family,
                        "group_id": group_id,
                        "split": split,
                        "sha256": sha,
                        "source_url": "fixture:unit-test",
                    })

        with self.manifest.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(manifest_rows[0]))
            writer.writeheader()
            writer.writerows(manifest_rows)

        self.protocol = freeze_protocol(
            self.manifest,
            self.study,
            {
                "bfree_fingerprint": {
                    "model_type": "fixture",
                    "checkpoint_sha256": "c" * 64,
                    "preprocess_sha256": "p" * 64,
                },
                "bootstrap_samples": 0,
            },
        )
        self.test_sources = [s for s in self.protocol["sources"] if s["split"] == "test"]
        self.conditions = [c["name"] for c in self.protocol["conditions"]]

    def _build_predictions(self, score_overrides: dict[tuple[str, str, str], float] | None = None) -> None:
        score_overrides = score_overrides or {}
        for detector in ("bfree", "frequency"):
            det_dir = self.study / "results" / detector
            det_dir.mkdir(parents=True, exist_ok=True)
            rows = []
            for source in self.test_sources:
                for cond in self.conditions:
                    default_score = 0.1 if source["label"] == 0 else 0.9
                    score = score_overrides.get((detector, source["source_id"], cond), default_score)
                    rows.append({
                        "source_id": source["source_id"],
                        "label": source["label"],
                        "generator": source["generator"],
                        "group_id": source["group_id"],
                        "split": source["split"],
                        "condition": cond,
                        "score": score,
                        "protocol_hash": self.protocol["protocol_hash"],
                    })
            (det_dir / "predictions.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
            )

    def test_equality_ties_and_group_pairing(self):
        # Equality at threshold=0.5 must be treated as negative (label 0):
        # - real (label=0) at 0.5 -> TN (FP=0)
        # - generated (label=1) at 0.5 -> FN (TP=0)
        # Also test pairing real row FP in alpha without affecting beta, and score ties.
        overrides = {
            # Pair real row in alpha (g-a1) to alpha via group_id -> FP=1 for alpha only
            ("bfree", "test-g-a1-0", "jpeg_q85_r1"): 0.8,
            # Equality at 0.5 for generated image in alpha & real image in beta
            ("bfree", "test-g-a1-1", "resize_s0.9_r3"): 0.5,
            ("bfree", "test-g-b1-0", "resize_s0.9_r3"): 0.5,
            # Exact score tie across classes in alpha (0.5 vs 0.5)
            ("bfree", "test-g-a1-0", "combined_q95_s0.9_r3"): 0.5,
            ("bfree", "test-g-a1-1", "combined_q95_s0.9_r3"): 0.5,
            # Frequency comparator misses in beta
            ("frequency", "test-g-b2-1", "baseline"): 0.2,
        }
        self._build_predictions(overrides)

        report = analyze_study(self.study, split="test")
        self.assertEqual(report["provenance"]["protocol_hash"], self.protocol["protocol_hash"])
        self.assertEqual(report["provenance"]["manifest_sha256"], self.protocol["manifest_sha256"])
        self.assertEqual(
            report["provenance"]["script_sha256"],
            hashlib.sha256((ROOT / "scripts" / "analyze_generator_errors.py").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            report["provenance"]["evaluator_sha256"],
            hashlib.sha256(Path(evaluation.__file__).read_bytes()).hexdigest(),
        )
        self.assertEqual(report["provenance"]["threshold"], 0.5)
        self.assertEqual(report["provenance"]["split"], "test")
        self.assertEqual(report["counts"]["matched_groups"], 4)
        self.assertEqual(report["counts"]["conditions"], 9)

        family_map = {
            (row["detector"], row["condition"], row["family"]): row
            for row in report["by_generator_family"]
        }
        agg_map = {
            (row["detector"], row["condition"]): row
            for row in report["aggregate_conditions"]
        }

        # Real FP in g-a1 pairs only to alpha, leaving beta unaffected
        alpha_jpeg = family_map[("bfree", "jpeg_q85_r1", "alpha")]
        beta_jpeg = family_map[("bfree", "jpeg_q85_r1", "beta")]
        self.assertEqual(alpha_jpeg["real_count"], 2)
        self.assertEqual(alpha_jpeg["generated_count"], 2)
        self.assertEqual(alpha_jpeg["fp"], 1)
        self.assertEqual(alpha_jpeg["fn"], 0)
        self.assertAlmostEqual(alpha_jpeg["balanced_accuracy"], 0.75)
        self.assertEqual(beta_jpeg["fp"], 0)
        self.assertEqual(beta_jpeg["fn"], 0)
        self.assertAlmostEqual(beta_jpeg["balanced_accuracy"], 1.0)

        # Equality at 0.5: generated=0.5 counts as FN, real=0.5 counts as TN (FP=0)
        alpha_r3 = family_map[("bfree", "resize_s0.9_r3", "alpha")]
        beta_r3 = family_map[("bfree", "resize_s0.9_r3", "beta")]
        self.assertEqual(alpha_r3["fn"], 1)
        self.assertEqual(alpha_r3["fp"], 0)
        self.assertAlmostEqual(alpha_r3["balanced_accuracy"], 0.75)
        self.assertEqual(beta_r3["fn"], 0)
        self.assertEqual(beta_r3["fp"], 0)
        self.assertAlmostEqual(beta_r3["balanced_accuracy"], 1.0)

        # Ties in combined_q95_s0.9_r3: alpha has scores real=[0.5, 0.1], gen=[0.5, 0.9]
        # Concordant pairs: (0.9 vs 0.5, 0.1) -> 2, (0.5 vs 0.1) -> 1, (0.5 vs 0.5) -> 0.5 => 3.5 / 4 = 0.875
        alpha_comb = family_map[("bfree", "combined_q95_s0.9_r3", "alpha")]
        self.assertEqual(alpha_comb["fn"], 1)
        self.assertEqual(alpha_comb["fp"], 0)
        self.assertAlmostEqual(alpha_comb["auroc"], 0.875)

        # Verify aggregate matches evaluate_rows directly
        bfree_rows = [
            json.loads(line)
            for line in (self.study / "results" / "bfree" / "predictions.jsonl").read_text().splitlines()
        ]
        canonical = evaluate_rows(bfree_rows, threshold=0.5, bootstrap_samples=0, seed=self.protocol["seed"])
        agg_r3 = agg_map[("bfree", "resize_s0.9_r3")]
        self.assertEqual(agg_r3["fn"], canonical["conditions"]["resize_s0.9_r3"]["confusion"]["fn"])
        self.assertEqual(agg_r3["fp"], canonical["conditions"]["resize_s0.9_r3"]["confusion"]["fp"])
        self.assertAlmostEqual(agg_r3["ece"], canonical["conditions"]["resize_s0.9_r3"]["metrics"]["ece"])
        self.assertAlmostEqual(agg_r3["auroc"], canonical["conditions"]["resize_s0.9_r3"]["metrics"]["auroc"])

    def test_cli_outputs_are_deterministic_and_render_figures(self):
        self._build_predictions()
        cmd = [sys.executable, str(ROOT / "scripts" / "analyze_generator_errors.py"), str(self.study)]
        first = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)

        paths = [
            self.study / "generator-error-analysis.json",
            self.study / "generator-error-analysis.csv",
            self.study / "condition-calibration-summary.csv",
            self.study / "figures" / "generator_error_breakdown.png",
            self.study / "figures" / "generator_error_breakdown.pdf",
        ]
        first_bytes = {p.name: p.read_bytes() for p in paths}
        for name, data in first_bytes.items():
            self.assertGreater(len(data), 0, f"{name} is empty")

        second = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(second.returncode, 0, second.stderr)
        for p in paths:
            self.assertEqual(p.read_bytes(), first_bytes[p.name], f"{p.name} was not deterministic")

    def test_missing_and_duplicate_coverage_rejected(self):
        self._build_predictions()
        pred_path = self.study / "results" / "bfree" / "predictions.jsonl"
        original_lines = pred_path.read_text(encoding="utf-8").splitlines()

        # Missing one prediction row
        pred_path.write_text("\n".join(original_lines[:-1]) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing"):
            analyze_study(self.study)

        # Duplicate row
        pred_path.write_text("\n".join(original_lines + [original_lines[0]]) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            analyze_study(self.study)

        # Restore and test wrong protocol_hash in prediction row
        tampered = json.loads(original_lines[0])
        tampered["protocol_hash"] = "0" * 64
        pred_path.write_text(
            "\n".join([json.dumps(tampered)] + original_lines[1:]) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "protocol_hash"):
            analyze_study(self.study)

    def test_incomplete_condition_set_and_unmatched_group_rejected(self):
        # 1. Incomplete condition set (fewer than 9 conditions)
        partial_dir = self.root / "study-partial"
        freeze_protocol(
            self.manifest,
            partial_dir,
            {
                "bfree_fingerprint": {
                    "model_type": "fixture",
                    "checkpoint_sha256": "c" * 64,
                    "preprocess_sha256": "p" * 64,
                },
                "conditions": DEFAULT_CONDITIONS[:3],
                "bootstrap_samples": 0,
            },
        )
        with self.assertRaisesRegex(ValueError, "nine-condition"):
            analyze_study(partial_dir)

        # 2. Unmatched group (missing synthetic member in test split)
        unmatched_manifest = self.root / "unmatched.csv"
        with self.manifest.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        rows = [r for r in rows if r["source_id"] != "test-g-b2-1"]
        with unmatched_manifest.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        unmatched_dir = self.root / "study-unmatched"
        freeze_protocol(
            unmatched_manifest,
            unmatched_dir,
            {
                "bfree_fingerprint": {
                    "model_type": "fixture",
                    "checkpoint_sha256": "c" * 64,
                    "preprocess_sha256": "p" * 64,
                },
                "bootstrap_samples": 0,
            },
        )
        with self.assertRaisesRegex(ValueError, "Matched group"):
            analyze_study(unmatched_dir)

    def test_archived_protocol_with_stale_code_fingerprint_loads_with_integrity_checks(self):
        protocol_path = self.study / "protocol.json"
        archived = json.loads(protocol_path.read_text(encoding="utf-8"))
        archived["code_fingerprint"]["files"]["benchmark.py"] = "0" * 64
        body = {key: value for key, value in archived.items() if key != "protocol_hash"}
        archived["protocol_hash"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()
        protocol_path.write_text(json.dumps(archived), encoding="utf-8")
        self.protocol = archived
        self._build_predictions()

        with self.assertRaisesRegex(ValueError, "Code or runtime versions changed"):
            load_protocol(protocol_path)

        report = analyze_study(self.study, split="test")
        self.assertEqual(report["provenance"]["protocol_hash"], archived["protocol_hash"])
        self.assertEqual(
            report["provenance"]["script_sha256"],
            hashlib.sha256((ROOT / "scripts" / "analyze_generator_errors.py").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            report["provenance"]["evaluator_sha256"],
            hashlib.sha256(Path(evaluation.__file__).read_bytes()).hexdigest(),
        )

        manifest_bytes = self.manifest.read_bytes()
        self.manifest.write_bytes(manifest_bytes + b"\n")
        with self.assertRaisesRegex(ValueError, "Manifest changed"):
            analyze_study(self.study, split="test")
        self.manifest.write_bytes(manifest_bytes)

        tampered = json.loads(protocol_path.read_text(encoding="utf-8"))
        tampered["threshold"] = 0.7
        protocol_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "altered"):
            analyze_study(self.study, split="test")


if __name__ == "__main__":
    unittest.main()
