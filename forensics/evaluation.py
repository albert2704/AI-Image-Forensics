"""Evaluate source-paired binary detector predictions without fitting on test data.

Input scores must be probabilities for label 1 (AI generated). No detector or
calibrator is fitted here. Run ``python -m forensics.evaluation --help`` for CSV
usage. Metrics are JSON safe: undefined quantities are None, never NaN.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np


BASELINE = "baseline"
ECE_BINS = 10
NLL_EPSILON = 1e-15
REQUIRED_COLUMNS = ("source_id", "label", "generator", "condition", "score")


def _validated_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    source_metadata: dict[str, tuple[int, str]] = {}
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"Row {number} must be a mapping.")
        missing = [key for key in REQUIRED_COLUMNS if key not in row]
        if missing:
            raise ValueError(f"Row {number} is missing columns: {', '.join(missing)}.")
        item = {}
        for key in ("source_id", "generator", "condition"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"Row {number}: {key} must be a nonempty string.")
            item[key] = row[key].strip()
        value = row["label"]
        if isinstance(value, bool) or value not in (0, 1, "0", "1"):
            raise ValueError(f"Row {number}: label must be 0 or 1.")
        item["label"] = int(value)
        try:
            if isinstance(row["score"], bool):
                raise ValueError
            score = float(row["score"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Row {number}: score must be a probability in [0, 1].") from exc
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"Row {number}: score must be finite and in [0, 1].")
        item["score"] = score
        key = (item["source_id"], item["condition"])
        if key in seen:
            raise ValueError(f"Duplicate source_id and condition: {key!r}.")
        seen.add(key)
        metadata = (item["label"], item["generator"])
        if item["source_id"] in source_metadata:
            if source_metadata[item["source_id"]] != metadata:
                raise ValueError(
                    f"Source {item['source_id']!r} has inconsistent label or generator."
                )
        source_metadata[item["source_id"]] = metadata
        result.append(item)
    return result


def _ranking_metrics(labels: np.ndarray, scores: np.ndarray) -> tuple[float | None, float | None]:
    """Mann-Whitney AUC with half-credit ties and grouped-threshold AP."""
    positives = int(labels.sum())
    negatives = len(labels) - positives
    if not positives or not negatives:
        # Explicit convention: avoid seemingly perfect AP on a one-class set.
        return None, None
    order = np.argsort(scores, kind="stable")
    sorted_scores, sorted_labels = scores[order], labels[order]
    group_starts = np.r_[0, np.flatnonzero(np.diff(sorted_scores)) + 1]
    group_ends = np.r_[group_starts[1:], len(labels)]
    negative_below = 0
    concordant = 0.0
    groups: list[tuple[int, int]] = []
    for start, end in zip(group_starts, group_ends):
        positive_count = int(sorted_labels[start:end].sum())
        negative_count = int(end - start - positive_count)
        concordant += positive_count * (negative_below + 0.5 * negative_count)
        negative_below += negative_count
        groups.append((positive_count, negative_count))
    true_positive = false_positive = 0
    average_precision = 0.0
    for positive_count, negative_count in reversed(groups):
        true_positive += positive_count
        false_positive += negative_count
        precision = true_positive / (true_positive + false_positive)
        average_precision += (positive_count / positives) * precision
    return concordant / (positives * negatives), average_precision


def _calibration_bins(labels: np.ndarray, scores: np.ndarray) -> tuple[float, list[dict[str, Any]]]:
    """Positive-class ECE, not top-label confidence ECE; bins are [lo, hi)."""
    edges = np.asarray([index / ECE_BINS for index in range(ECE_BINS + 1)])
    # Internal boundaries belong to the bin on the right; score 1 is in bin 9.
    bin_ids = np.clip(np.searchsorted(edges, scores, side="right") - 1, 0, ECE_BINS - 1)
    total = len(labels)
    ece = 0.0
    bins: list[dict[str, Any]] = []
    for index in range(ECE_BINS):
        selected = bin_ids == index
        count = int(selected.sum())
        mean_score = float(scores[selected].mean()) if count else None
        positive_fraction = float(labels[selected].mean()) if count else None
        gap = abs(mean_score - positive_fraction) if count else None
        weighted_gap = (count / total) * gap if count else 0.0
        ece += weighted_gap
        bins.append({
            "lower": float(edges[index]),
            "upper": float(edges[index + 1]),
            "upper_inclusive": index == ECE_BINS - 1,
            "count": count,
            "mean_score": mean_score,
            "positive_fraction": positive_fraction,
            "absolute_gap": gap,
            "weighted_gap": weighted_gap,
        })
    return float(ece), bins


def _condition_metrics(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    labels = np.asarray([row["label"] for row in rows], dtype=np.int64)
    scores = np.asarray([row["score"] for row in rows], dtype=np.float64)
    predicted = scores > threshold
    positive = labels == 1
    negative = ~positive
    tp = int(np.sum(predicted & positive))
    fp = int(np.sum(predicted & negative))
    tn = int(np.sum(~predicted & negative))
    fn = int(np.sum(~predicted & positive))
    positive_count, negative_count = tp + fn, tn + fp
    tpr = tp / positive_count if positive_count else None
    fpr = fp / negative_count if negative_count else None
    balanced_accuracy = (tpr + 1 - fpr) / 2 if tpr is not None and fpr is not None else None
    auroc, average_precision = _ranking_metrics(labels, scores)
    ece, bins = _calibration_bins(labels, scores)
    clipped = np.clip(scores, NLL_EPSILON, 1 - NLL_EPSILON)
    reasons = {}
    if not positive_count or not negative_count:
        reason = "Both label classes are required; this condition contains only one class."
        reasons.update({key: reason for key in ("auroc", "average_precision", "balanced_accuracy")})
    if not positive_count:
        reasons["tpr"] = "No positive sources in this condition."
    if not negative_count:
        reasons["fpr"] = "No negative sources in this condition."
    return {
        "counts": {
            "sources": len(rows), "positive": positive_count, "negative": negative_count,
            "by_generator": dict(sorted(Counter(row["generator"] for row in rows).items())),
        },
        "metrics": {
            "auroc": auroc,
            "average_precision": average_precision,
            "balanced_accuracy": balanced_accuracy,
            "tpr": tpr,
            "fpr": fpr,
            "accuracy": (tp + tn) / len(rows),
            "brier": float(np.mean((scores - labels) ** 2)),
            "nll": float(-np.mean(labels * np.log(clipped) + (1 - labels) * np.log1p(-clipped))),
            "ece": ece,
        },
        "confusion": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "ece_bins": bins,
        "metric_reasons": reasons,
    }


def _paired_metrics(
    baseline: dict[str, dict[str, Any]],
    condition: dict[str, dict[str, Any]],
    threshold: float,
    bootstrap_samples: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    source_ids = sorted(baseline.keys() & condition.keys())
    labels = np.asarray([baseline[key]["label"] for key in source_ids], dtype=np.int64)
    before = np.asarray([baseline[key]["score"] for key in source_ids], dtype=np.float64)
    after = np.asarray([condition[key]["score"] for key in source_ids], dtype=np.float64)
    positive = np.flatnonzero(labels == 1)
    negative = np.flatnonzero(labels == 0)
    before_decisions, after_decisions = before > threshold, after > threshold
    difference = after - before
    correctness_change = (after_decisions == labels).astype(float) - (before_decisions == labels).astype(float)
    paired_count = len(source_ids)
    result: dict[str, Any] = {
        "baseline_condition": BASELINE,
        "counts": {
            "baseline_sources": len(baseline), "condition_sources": len(condition),
            "paired_sources": paired_count, "paired_positive": len(positive), "paired_negative": len(negative),
            "condition_sources_without_baseline": len(condition.keys() - baseline.keys()),
            "baseline_sources_without_condition": len(baseline.keys() - condition.keys()),
        },
        "score_delta": {
            "direction": "condition minus baseline",
            "mean": float(difference.mean()) if paired_count else None,
            "median": float(np.median(difference)) if paired_count else None,
            "mean_absolute": float(np.abs(difference).mean()) if paired_count else None,
            "mean_positive": float(difference[positive].mean()) if len(positive) else None,
            "mean_negative": float(difference[negative].mean()) if len(negative) else None,
        },
        "label_flip_rate": float(np.mean(before_decisions != after_decisions)) if paired_count else None,
        "flips": {
            "negative_to_positive": int(np.sum(~before_decisions & after_decisions)),
            "positive_to_negative": int(np.sum(before_decisions & ~after_decisions)),
        },
        "balanced_accuracy_delta": None,
        "baseline_balanced_accuracy_on_pairs": None,
        "condition_balanced_accuracy_on_pairs": None,
        "balanced_accuracy_delta_ci95": None,
        "bootstrap": {
            "method": "class-stratified paired source-image percentile bootstrap",
            "requested_samples": bootstrap_samples,
            "valid_samples": 0,
            "confidence_level": 0.95,
            "resampling_unit": "source_id with baseline and condition kept together",
            "class_counts_fixed": True,
        },
        "reason": None,
    }
    if not paired_count:
        result["reason"] = "No shared source_id between baseline and this condition."
        return result
    if not len(positive) or not len(negative):
        result["reason"] = "Paired balanced accuracy requires both label classes in the shared sources."
        return result
    for name, decisions in (("baseline", before_decisions), ("condition", after_decisions)):
        result[f"{name}_balanced_accuracy_on_pairs"] = float(
            (np.mean(decisions[positive]) + np.mean(~decisions[negative])) / 2
        )
    result["balanced_accuracy_delta"] = float(
        (correctness_change[positive].mean() + correctness_change[negative].mean()) / 2
    )
    if not bootstrap_samples:
        result["reason"] = "Bootstrap disabled: bootstrap_samples is 0."
        return result
    if len(positive) < 2 or len(negative) < 2:
        result["reason"] = "At least two paired source images per class are required for an informative bootstrap interval."
        return result
    deltas = np.empty(bootstrap_samples, dtype=np.float64)
    for index in range(bootstrap_samples):
        # Each draw selects a source and retains both of its paired predictions.
        positive_draw = rng.choice(positive, size=len(positive), replace=True)
        negative_draw = rng.choice(negative, size=len(negative), replace=True)
        deltas[index] = (correctness_change[positive_draw].mean() + correctness_change[negative_draw].mean()) / 2
    result["balanced_accuracy_delta_ci95"] = [float(x) for x in np.quantile(deltas, [0.025, 0.975])]
    result["bootstrap"]["valid_samples"] = bootstrap_samples
    return result


def evaluate_rows(
    rows: Iterable[Mapping[str, Any]],
    threshold: float = 0.5,
    bootstrap_samples: int = 1000,
    seed: int = 2026,
) -> dict[str, Any]:
    """Return per-condition metrics and paired changes from ``baseline``.

    A row needs source_id, label, generator, condition, and score. Each source is
    one independent original image. Labels and generator metadata must stay
    stable across variants. Duplicate source/condition pairs are rejected.
    Thresholds are fixed inputs; this function never optimizes a test threshold.
    Bootstrap intervals condition on observed class counts and pair availability.
    """
    try:
        if isinstance(threshold, bool):
            raise ValueError
        threshold = float(threshold)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("threshold must be finite and in [0, 1].") from exc
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be finite and in [0, 1].")
    if isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, (int, np.integer)) or bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be a nonnegative integer.")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("seed must be a nonnegative integer.")
    bootstrap_samples, seed = int(bootstrap_samples), int(seed)
    clean_rows = _validated_rows(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in clean_rows:
        grouped[row["condition"]].append(row)
    # Deterministic input ordering also stabilizes floating point reductions.
    for condition in grouped:
        grouped[condition].sort(key=lambda row: row["source_id"])
    baseline = {row["source_id"]: row for row in grouped.get(BASELINE, [])}
    condition_names = sorted(grouped)
    rng = np.random.default_rng(seed)
    warnings = []
    if not clean_rows:
        warnings.append("No prediction rows supplied; no measured dataset results are available.")
    elif not baseline:
        warnings.append("No condition named 'baseline'; paired results are unavailable.")
    return {
        "schema_version": "1.0",
        "positive_label": 1,
        "positive_label_meaning": "AI generated",
        "threshold": threshold,
        "decision_rule": "score > threshold predicts label 1; equality predicts label 0",
        "counts": {
            "rows": len(clean_rows),
            "independent_sources": len({row["source_id"] for row in clean_rows}),
            "conditions": len(grouped),
        },
        "methodology": {
            "auroc": "positive-negative concordance; score ties receive half credit",
            "average_precision": "sum of recall increments times precision at distinct score thresholds; ties grouped",
            "missing_class_policy": "AUROC, AP and balanced accuracy are null unless both classes are present",
            "ece": "positive-class calibration error, 10 equal-width probability bins; [lower, upper), final bin includes 1",
            "nll": "binary negative log likelihood, natural logarithm",
            "nll_probability_clip": NLL_EPSILON,
            "bootstrap_seed": seed,
            "threshold_fitting": "none; select and freeze using validation data before test evaluation",
        },
        "conditions": {name: _condition_metrics(grouped[name], threshold) for name in condition_names},
        "paired_vs_baseline": {
            name: _paired_metrics(
                baseline, {row["source_id"]: row for row in grouped[name]}, threshold, bootstrap_samples, rng
            )
            for name in condition_names if name != BASELINE
        },
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path, help="CSV with source_id,label,generator,condition,score")
    parser.add_argument("--output", "-o", type=Path, help="Write JSON here (default: stdout)")
    parser.add_argument("--threshold", type=float, default=0.5, help="Frozen threshold; no test fitting (default: 0.5)")
    parser.add_argument("--bootstrap-samples", type=int, default=1000, help="Paired source resamples, 0 disables intervals")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args(argv)
    try:
        with args.predictions.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}.")
            report = evaluate_rows(reader, args.threshold, args.bootstrap_samples, args.seed)
        serialized = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
        else:
            print(serialized, end="")
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
