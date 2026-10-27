"""Independent, read-only audit of completed detector journals.

No project evaluation, benchmark, detector or pipeline module is imported.
AUROC, balanced accuracy and confusion counts are independently computed with
scikit-learn. Bootstrap samples reconstruct the actual paired labels/predictions
and call scikit-learn on each resampled dataset instead of using project totals.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform

import numpy as np
import sklearn
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "output" / "benchmark"
DESTINATION = ROOT / "output" / "verification" / "independent-metric-check.json"
TOLERANCE = 1e-12


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(actual, expected, description):
    if not np.allclose(actual, expected, rtol=0, atol=TOLERANCE):
        raise AssertionError(f"{description}: independently computed {actual!r}, project {expected!r}")


def journal(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def audit_detector(detector, protocol):
    directory = STUDY / "results" / detector
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text())
    if summary["protocol_hash"] != protocol["protocol_hash"] or summary["detector_id"] != detector:
        raise AssertionError("Summary identity differs from frozen protocol/detector.")
    test_summary = summary["splits"]["test"]
    if not test_summary["coverage"]["complete"]:
        raise ValueError(f"{detector}: refusing to audit or report final values from incomplete test results.")
    path = directory / "predictions.jsonl"
    journal_hash_before = file_hash(path)
    rows = journal(path)
    model = json.loads((directory / "model.json").read_text())
    model_hash = digest(model)
    expected = {source["source_id"]: source for source in protocol["sources"]}
    conditions = [condition["name"] for condition in protocol["conditions"]]
    test_ids = sorted(source_id for source_id, source in expected.items() if source["split"] == "test")
    if len(test_ids) != 192 or len(conditions) != 9:
        raise AssertionError("Unexpected frozen study dimensions.")
    if detector == "bfree" and model != protocol["bfree_fingerprint"]:
        raise AssertionError("B-Free model identity differs from protocol.")
    if detector == "frequency":
        training_ids = sorted(source_id for source_id, source in expected.items() if source["split"] == "train")
        if sorted(model["training_source_ids"]) != training_ids or model["protocol_hash"] != protocol["protocol_hash"]:
            raise AssertionError("Frequency model does not bind exclusively to frozen training source IDs.")
        if set(model["training_source_ids"]) & set(test_ids):
            raise AssertionError("Training/test overlap in frequency model provenance.")
    seen, by_condition = set(), {condition: {} for condition in conditions}
    for row in rows:
        key = row["source_id"], row["condition"]
        if key in seen or key[0] not in expected or key[1] not in conditions:
            raise AssertionError("Duplicate or unexpected source/condition in journal.")
        seen.add(key)
        source = expected[key[0]]
        if any(row[field] != source[field] for field in ("label", "generator", "group_id", "split")):
            raise AssertionError("Source labels, group or split differ across variants or from protocol.")
        if row["source_sha256"] != source["sha256"] or row["protocol_hash"] != protocol["protocol_hash"] or row["model_fingerprint_sha256"] != model_hash or row["detector_id"] != detector:
            raise AssertionError("Prediction provenance does not match source/model/protocol.")
        score = row["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1 or row["prediction"]["score"] != score:
            raise AssertionError("Invalid or inconsistent score.")
        if row["condition"] == "baseline" and row["pixel_sha256"] != source["pixel_sha256"]:
            raise AssertionError("Baseline pixels differ from frozen source pixels.")
        if row["split"] == "test":
            by_condition[key[1]][key[0]] = row
    for condition in conditions:
        if set(by_condition[condition]) != set(test_ids):
            raise AssertionError(f"Missing or extra held-out identities in {condition}.")
    held_out = [row for row in rows if row["split"] == "test"]
    if len(held_out) != 1728 or test_summary["coverage"]["actual_predictions"] != 1728:
        raise AssertionError("Held-out journal/summary count mismatch.")
    failures = journal(directory / "failures.jsonl")
    if summary["failure_attempts"] != len(failures):
        raise AssertionError("Failure-attempt count mismatch.")
    threshold = protocol["threshold"]
    independently_computed = {}
    for condition in conditions:
        ordered = [by_condition[condition][source_id] for source_id in test_ids]
        truth = np.array([row["label"] for row in ordered], dtype=np.int64)
        scores = np.array([row["score"] for row in ordered], dtype=np.float64)
        predicted = scores > threshold
        auc = float(roc_auc_score(truth, scores))
        bacc = float(balanced_accuracy_score(truth, predicted))
        tn, fp, fn, tp = map(int, confusion_matrix(truth, predicted, labels=[0, 1]).ravel())
        reference = test_summary["conditions"][condition]
        close(auc, reference["metrics"]["auroc"], f"{detector}/{condition} AUROC")
        close(bacc, reference["metrics"]["balanced_accuracy"], f"{detector}/{condition} balanced accuracy")
        confusion = {"tn": tn, "fp": fp, "fn": fn, "tp": tp}
        if confusion != reference["confusion"]:
            raise AssertionError("Confusion counts mismatch.")
        independently_computed[condition] = {"sources": len(ordered), "labels": dict(Counter(map(int, truth))),
            "auroc": auc, "balanced_accuracy": bacc, "confusion": confusion,
            "auroc_absolute_difference": abs(auc-reference["metrics"]["auroc"]),
            "balanced_accuracy_absolute_difference": abs(bacc-reference["metrics"]["balanced_accuracy"])}
    members = {}
    for source_id in test_ids:
        members.setdefault(expected[source_id]["group_id"], []).append(source_id)
    groups = sorted(members)
    if len(groups) != 96:
        raise AssertionError("Wrong number of held-out matched groups.")
    for group in groups:
        members[group].sort(key=lambda source_id: expected[source_id]["label"])
        if [expected[source_id]["label"] for source_id in members[group]] != [0, 1]:
            raise AssertionError("A matched group does not contain exactly one real and one generated source.")
    source_matrix = [members[group] for group in groups]
    truth_matrix = np.array([[expected[source_id]["label"] for source_id in ids] for ids in source_matrix])
    baseline_matrix = np.array([[by_condition["baseline"][source_id]["score"] > threshold for source_id in ids] for ids in source_matrix])
    primary_matrix = np.array([[by_condition["jpeg_q85_r3"][source_id]["score"] > threshold for source_id in ids] for ids in source_matrix])
    rng = np.random.default_rng(protocol["seed"])
    draws = []
    for _ in range(protocol["bootstrap_samples"]):
        sample = rng.integers(0, len(groups), size=len(groups))
        # Reconstruct each paired resampled dataset, then invoke an independent
        # metric library on the original and transformed predictions separately.
        labels = truth_matrix[sample].ravel()
        before = balanced_accuracy_score(labels, baseline_matrix[sample].ravel())
        after = balanced_accuracy_score(labels, primary_matrix[sample].ravel())
        draws.append(float(after-before))
    interval = np.quantile(draws, [.025, .975]).tolist()
    point = independently_computed["jpeg_q85_r3"]["balanced_accuracy"] - independently_computed["baseline"]["balanced_accuracy"]
    primary = test_summary["paired_vs_baseline"]["jpeg_q85_r3"]
    close(point, primary["balanced_accuracy_delta"], f"{detector} primary point change")
    close(interval, primary["balanced_accuracy_delta_ci95"], f"{detector} primary CI")
    if primary["bootstrap"]["paired_sources"] != 192 or primary["bootstrap"]["paired_groups"] != 96 or primary["bootstrap"]["valid_samples"] != 5000 or primary["bootstrap"]["invalid_samples"] != 0:
        raise AssertionError("Primary bootstrap group/source/sample counts mismatch.")
    if file_hash(path) != journal_hash_before:
        raise AssertionError("Prediction journal changed during audit.")
    return {"status": "passed", "journal_rows_all_splits": len(rows), "journal_sha256": journal_hash_before,
            "summary_sha256": file_hash(summary_path), "model_sha256": file_hash(directory / "model.json"),
            "held_out_predictions": len(held_out), "held_out_sources": len(test_ids), "held_out_groups": len(groups),
            "failure_attempts": len(failures), "unique_source_condition_pairs": len(seen),
            "all_conditions_have_identical_held_out_source_ids": True, "source_and_model_provenance_verified": True,
            "score_origins": dict(Counter(row.get("score_origin") for row in held_out)),
            "conditions": independently_computed,
            "primary_jpeg_q85_r3": {"balanced_accuracy_delta": point, "ci95": interval,
                "bootstrap_draws": len(draws), "seed": protocol["seed"], "paired_groups": len(groups),
                "paired_sources": len(test_ids), "all_draws_preserve_real_generated_pairs": True,
                "implementation": "Reconstruct paired predictions for each group sample; sklearn balanced_accuracy_score(after) minus sklearn balanced_accuracy_score(before); NumPy percentile interval."}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detectors", nargs="+", choices=["frequency", "bfree"], default=["frequency", "bfree"])
    args = parser.parse_args()
    protocol_path = STUDY / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    if digest({key: value for key, value in protocol.items() if key != "protocol_hash"}) != protocol["protocol_hash"]:
        raise AssertionError("Frozen protocol digest is invalid.")
    if protocol["seed"] != 20261018 or protocol["bootstrap_samples"] != 5000 or protocol["threshold"] != .5:
        raise AssertionError("Unexpected prespecified analysis settings.")
    result = json.loads(DESTINATION.read_text()) if DESTINATION.exists() else {"detectors": {}}
    if result.get("protocol_hash", protocol["protocol_hash"]) != protocol["protocol_hash"]:
        raise AssertionError("Prior audit belongs to another study.")
    result.update({"protocol_hash": protocol["protocol_hash"], "protocol_file_sha256": file_hash(protocol_path),
        "audit_script_sha256": file_hash(__file__), "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "sklearn": sklearn.__version__},
        "absolute_tolerance": TOLERANCE, "threshold_rule": "score > 0.5",
        "independence": "No project metric or detector function is imported; no inference is run.",
        "scope": "Arithmetic, source identities, pairing, recorded provenance and frozen bootstrap recipe; not independent ground-truth verification or a guarantee of statistical group independence."})
    for detector in args.detectors:
        result["detectors"][detector] = audit_detector(detector, protocol)
        result["status"] = "passed" if set(result["detectors"]) == {"frequency", "bfree"} else "partial_audit_completed_detectors_only"
        temporary = DESTINATION.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        temporary.replace(DESTINATION)
        print(json.dumps({"detector": detector, "status": "passed", "primary": result["detectors"][detector]["primary_jpeg_q85_r3"]}), flush=True)
    print(DESTINATION, flush=True)


if __name__ == "__main__":
    main()
