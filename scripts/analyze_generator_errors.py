#!/usr/bin/env python3
"""Analyze held-out threshold errors and calibration by generator family and condition.

Reuses canonical metrics from ``forensics.evaluation.evaluate_rows`` and
frozen protocol validation from ``forensics.benchmark.load_protocol``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forensics.benchmark import DEFAULT_CONDITIONS, SPLITS, load_protocol
from forensics.evaluation import BASELINE, evaluate_rows


DETECTORS = (
    ("bfree", "B-Free"),
    ("frequency", "FFT/DCT + logistic regression"),
)

CONDITION_TITLES = {
    "baseline": "Baseline",
    "jpeg_q85_r1": "JPEG Q85, round 1",
    "jpeg_q85_r3": "JPEG Q85, round 3",
    "resize_s0.9_r1": "Resize ×0.9, round 1",
    "resize_s0.9_r3": "Resize ×0.9, round 3",
    "combined_q95_s0.9_r1": "Resize → JPEG Q95, round 1",
    "combined_q95_s0.9_r3": "Resize → JPEG Q95, round 3",
    "reverse_q95_s0.9_r3": "JPEG Q95 → resize, round 3",
    "independent_q95_s0.9_r3": "Single pass at round 3 size, Q95",
}

PLOT_CONDITION_LABELS = {
    "baseline": "Baseline",
    "jpeg_q85_r1": "JPEG 85\n1 round",
    "jpeg_q85_r3": "JPEG 85\n3 rounds",
    "resize_s0.9_r1": "Resize .9\n1 round",
    "resize_s0.9_r3": "Resize .9\n3 rounds",
    "combined_q95_s0.9_r1": "Resize → JPEG 95\n1 round",
    "combined_q95_s0.9_r3": "Resize → JPEG 95\n3 rounds",
    "reverse_q95_s0.9_r3": "JPEG 95 → resize\n3 rounds",
    "independent_q95_s0.9_r3": "Single pass\nmatched size",
}

FAMILY_LABELS = {
    "dalle3": "DALL-E 3",
    "firefly": "Firefly",
    "midjourney-v5": "Midjourney v5",
    "stable-diffusion-xl": "Stable Diffusion XL",
}

FAMILY_COLORS = {
    "dalle3": "#1967a3",
    "firefly": "#d97706",
    "midjourney-v5": "#0f8b6d",
    "stable-diffusion-xl": "#8b5cf6",
}

FALLBACK_PALETTE = ("#1967a3", "#d97706", "#0f8b6d", "#8b5cf6", "#a04968", "#4b5563")

FAMILY_CSV_FIELDS = [
    "detector",
    "detector_label",
    "condition",
    "condition_label",
    "family",
    "matched_groups",
    "real_count",
    "generated_count",
    "tp",
    "fp",
    "tn",
    "fn",
    "tpr",
    "fpr",
    "balanced_accuracy",
    "auroc",
    "average_precision",
    "brier",
    "nll",
    "ece",
    "protocol_hash",
    "threshold",
    "split",
]

AGGREGATE_CSV_FIELDS = [
    "detector",
    "detector_label",
    "condition",
    "condition_label",
    "real_count",
    "generated_count",
    "tp",
    "fp",
    "tn",
    "fn",
    "tpr",
    "fpr",
    "balanced_accuracy",
    "auroc",
    "average_precision",
    "brier",
    "nll",
    "ece",
    "protocol_hash",
    "threshold",
    "split",
]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing predictions file: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_no, raw in enumerate(stream, start=1):
            try:
                item = json.loads(raw)
            except ValueError as exc:
                raise ValueError(f"Invalid JSON on line {line_no} of {path}.") from exc
            if not isinstance(item, dict):
                raise ValueError(f"Line {line_no} of {path} must be a JSON object.")
            rows.append(item)
    return rows


def _validate_protocol_and_groups(
    protocol: dict[str, Any], split: str
) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, str]]:
    if split not in SPLITS:
        raise ValueError(f"Split must be one of {SPLITS}, got {split!r}.")

    condition_names = [cond["name"] for cond in protocol["conditions"]]
    expected_condition_set = {cond["name"] for cond in DEFAULT_CONDITIONS}
    if len(condition_names) != len(expected_condition_set) or set(condition_names) != expected_condition_set:
        raise ValueError(
            "Complete nine-condition coverage requires the 9 prespecified benchmark conditions."
        )
    if BASELINE not in condition_names:
        raise ValueError("Protocol conditions must include baseline.")

    split_sources = [row for row in protocol["sources"] if row["split"] == split]
    if not split_sources:
        raise ValueError(f"Protocol has no sources for split {split!r}.")

    source_by_id = {row["source_id"]: row for row in split_sources}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in split_sources:
        groups[row["group_id"]].append(row)

    family_by_group: dict[str, str] = {}
    for group_id in sorted(groups):
        members = groups[group_id]
        labels = [int(member["label"]) for member in members]
        if len(members) != 2 or sorted(labels) != [0, 1]:
            raise ValueError(
                f"Matched group {group_id!r} in split {split!r} must contain exactly one real (0) and one generated (1) source."
            )
        synthetic = next(member for member in members if int(member["label"]) == 1)
        family = synthetic["generator"]
        if not isinstance(family, str) or not family.strip() or family.strip() == "real":
            raise ValueError(f"Group {group_id!r} has invalid synthetic generator {family!r}.")
        family_by_group[group_id] = family.strip()

    return condition_names, source_by_id, family_by_group


def _load_and_validate_detector_rows(
    study: Path,
    detector: str,
    protocol: dict[str, Any],
    split: str,
    condition_names: list[str],
    source_by_id: dict[str, dict[str, Any]],
    family_by_group: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pred_path = study / "results" / detector / "predictions.jsonl"
    all_rows = _read_jsonl(pred_path)
    protocol_hash = protocol["protocol_hash"]

    summary_path = study / "results" / detector / "summary.json"
    summary_hash = None
    if summary_path.exists():
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_data.get("protocol_hash") != protocol_hash:
            raise ValueError(f"{detector} summary.json protocol_hash does not match protocol.json.")
        summary_hash = _sha256_file(summary_path)

    model_path = study / "results" / detector / "model.json"
    model_hash = _sha256_file(model_path) if model_path.exists() else None

    split_rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    by_condition_group: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    required_fields = {"source_id", "label", "generator", "group_id", "split", "condition", "score", "protocol_hash"}

    for index, row in enumerate(all_rows, start=1):
        if row.get("protocol_hash") != protocol_hash:
            raise ValueError(f"{detector} prediction row {index} has mismatched protocol_hash.")
        if row.get("split") != split:
            continue
        missing_fields = sorted(required_fields - set(row.keys()))
        if missing_fields:
            raise ValueError(f"{detector} prediction row {index} missing fields: {', '.join(missing_fields)}.")
        source_id = row["source_id"]
        if source_id not in source_by_id:
            raise ValueError(f"{detector} prediction row {index} references unknown split source_id {source_id!r}.")
        expected_source = source_by_id[source_id]
        if (
            int(row["label"]) != int(expected_source["label"])
            or row["generator"] != expected_source["generator"]
            or row["group_id"] != expected_source["group_id"]
        ):
            raise ValueError(f"{detector} prediction row {index} metadata differs from protocol for {source_id!r}.")
        condition = row["condition"]
        if condition not in condition_names:
            raise ValueError(f"{detector} prediction row {index} has unexpected condition {condition!r}.")
        pair = (source_id, condition)
        if pair in seen_pairs:
            raise ValueError(f"Duplicate {detector} prediction for {pair!r}.")
        seen_pairs.add(pair)
        by_condition_group[(condition, row["group_id"])][int(row["label"])] = row
        split_rows.append(row)

    expected_pairs = {(source_id, cond) for source_id in source_by_id for cond in condition_names}
    missing = expected_pairs - seen_pairs
    if missing:
        first_missing = sorted(missing)[0]
        raise ValueError(
            f"{detector} is missing {len(missing)} prediction(s) in split {split!r}; first missing: {first_missing!r}."
        )

    for condition in condition_names:
        for group_id, expected_family in family_by_group.items():
            members = by_condition_group.get((condition, group_id), {})
            if set(members) != {0, 1}:
                raise ValueError(
                    f"{detector} condition {condition!r} group {group_id!r} does not have matched real and generated rows."
                )
            if members[1]["generator"] != expected_family:
                raise ValueError(
                    f"{detector} baseline/condition generator mismatch for group {group_id!r}: {members[1]['generator']!r} != {expected_family!r}."
                )

    split_rows.sort(key=lambda r: (r["source_id"], condition_names.index(r["condition"])))
    provenance = {
        "predictions_jsonl": str(pred_path.relative_to(study)) if pred_path.is_relative_to(study) else str(pred_path),
        "predictions_jsonl_sha256": _sha256_file(pred_path),
        "model_json_sha256": model_hash,
        "summary_json_sha256": summary_hash,
        "rows_total": len(all_rows),
        "rows_in_split": len(split_rows),
    }
    return split_rows, provenance


def analyze_study(study: Path, split: str = "test") -> dict[str, Any]:
    """Run canonical generator-error and calibration analysis for a frozen study."""
    study = Path(study)
    protocol_path = study / "protocol.json"
    protocol = load_protocol(protocol_path)
    condition_names, source_by_id, family_by_group = _validate_protocol_and_groups(protocol, split)
    families = sorted(set(family_by_group.values()))
    groups_per_family = {
        fam: sum(1 for group_fam in family_by_group.values() if group_fam == fam)
        for fam in families
    }

    threshold = float(protocol["threshold"])
    seed = int(protocol["seed"])

    detector_provenance: dict[str, Any] = {}
    aggregate_rows: list[dict[str, Any]] = []
    family_rows_out: list[dict[str, Any]] = []
    error_concentration: dict[str, Any] = {}
    methodology: dict[str, Any] | None = None

    for detector, detector_label in DETECTORS:
        split_rows, det_prov = _load_and_validate_detector_rows(
            study, detector, protocol, split, condition_names, source_by_id, family_by_group
        )
        detector_provenance[detector] = det_prov

        agg_report = evaluate_rows(split_rows, threshold=threshold, bootstrap_samples=0, seed=seed)
        if methodology is None:
            methodology = agg_report["methodology"]

        fam_reports: dict[str, dict[str, Any]] = {}
        for fam in families:
            fam_input = [row for row in split_rows if family_by_group[row["group_id"]] == fam]
            fam_reports[fam] = evaluate_rows(fam_input, threshold=threshold, bootstrap_samples=0, seed=seed)

        det_concentration: dict[str, Any] = {}
        total_fn_all_conditions = 0
        total_fp_all_conditions = 0
        fn_by_family_all_conditions: dict[str, int] = {fam: 0 for fam in families}
        fp_by_family_all_conditions: dict[str, int] = {fam: 0 for fam in families}

        for condition in condition_names:
            cond_label = CONDITION_TITLES.get(condition, condition)
            cond_data = agg_report["conditions"][condition]
            metrics = cond_data["metrics"]
            confusion = cond_data["confusion"]
            counts = cond_data["counts"]

            fn_by_fam = {fam: fam_reports[fam]["conditions"][condition]["confusion"]["fn"] for fam in families}
            fp_by_fam = {fam: fam_reports[fam]["conditions"][condition]["confusion"]["fp"] for fam in families}
            assert sum(fn_by_fam.values()) == confusion["fn"]
            assert sum(fp_by_fam.values()) == confusion["fp"]

            total_fn_all_conditions += confusion["fn"]
            total_fp_all_conditions += confusion["fp"]
            for fam in families:
                fn_by_family_all_conditions[fam] += fn_by_fam[fam]
                fp_by_family_all_conditions[fam] += fp_by_fam[fam]

            aggregate_rows.append({
                "detector": detector,
                "detector_label": detector_label,
                "condition": condition,
                "condition_label": cond_label,
                "real_count": counts["negative"],
                "generated_count": counts["positive"],
                "tp": confusion["tp"],
                "fp": confusion["fp"],
                "tn": confusion["tn"],
                "fn": confusion["fn"],
                "tpr": metrics["tpr"],
                "fpr": metrics["fpr"],
                "balanced_accuracy": metrics["balanced_accuracy"],
                "accuracy": metrics["accuracy"],
                "auroc": metrics["auroc"],
                "average_precision": metrics["average_precision"],
                "brier": metrics["brier"],
                "nll": metrics["nll"],
                "ece": metrics["ece"],
                "fn_by_family": fn_by_fam,
                "fp_by_family": fp_by_fam,
                "ece_bins": cond_data["ece_bins"],
            })

            for fam in families:
                f_data = fam_reports[fam]["conditions"][condition]
                f_metrics = f_data["metrics"]
                f_conf = f_data["confusion"]
                f_counts = f_data["counts"]
                family_rows_out.append({
                    "detector": detector,
                    "detector_label": detector_label,
                    "condition": condition,
                    "condition_label": cond_label,
                    "family": fam,
                    "matched_groups": groups_per_family[fam],
                    "real_count": f_counts["negative"],
                    "generated_count": f_counts["positive"],
                    "tp": f_conf["tp"],
                    "fp": f_conf["fp"],
                    "tn": f_conf["tn"],
                    "fn": f_conf["fn"],
                    "tpr": f_metrics["tpr"],
                    "fpr": f_metrics["fpr"],
                    "balanced_accuracy": f_metrics["balanced_accuracy"],
                    "auroc": f_metrics["auroc"],
                    "average_precision": f_metrics["average_precision"],
                    "brier": f_metrics["brier"],
                    "nll": f_metrics["nll"],
                    "ece": f_metrics["ece"],
                })

            det_concentration[condition] = {
                "total_fn": confusion["fn"],
                "total_fp": confusion["fp"],
                "fn_by_family": fn_by_fam,
                "fp_by_family": fp_by_fam,
            }

        error_concentration[detector] = {
            "total_fn_across_conditions": total_fn_all_conditions,
            "total_fp_across_conditions": total_fp_all_conditions,
            "fn_by_family_across_conditions": fn_by_family_all_conditions,
            "fp_by_family_across_conditions": fp_by_family_all_conditions,
            "by_condition": det_concentration,
        }

    return {
        "schema_version": "1.0",
        "script": "scripts/analyze_generator_errors.py",
        "provenance": {
            "split": split,
            "threshold": threshold,
            "decision_rule": "score > threshold predicts label 1; equality predicts label 0",
            "protocol_hash": protocol["protocol_hash"],
            "protocol_json_sha256": _sha256_file(protocol_path),
            "manifest_sha256": protocol["manifest_sha256"],
            "detectors": detector_provenance,
        },
        "counts": {
            "conditions": len(condition_names),
            "condition_names": condition_names,
            "matched_groups": len(family_by_group),
            "sources_in_split": len(source_by_id),
            "real_sources": sum(1 for row in source_by_id.values() if int(row["label"]) == 0),
            "generated_sources": sum(1 for row in source_by_id.values() if int(row["label"]) == 1),
            "families": families,
            "groups_per_family": groups_per_family,
        },
        "methodology": methodology,
        "error_concentration": error_concentration,
        "aggregate_conditions": aggregate_rows,
        "by_generator_family": family_rows_out,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]], provenance: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "protocol_hash": provenance["protocol_hash"],
                "threshold": provenance["threshold"],
                "split": provenance["split"],
            })


def render_figure(report: dict[str, Any], output_dir: Path, stem: str = "generator_error_breakdown") -> list[Path]:
    """Render deterministic PNG and PDF error-by-generator breakdown figure."""
    output_dir.mkdir(parents=True, exist_ok=True)
    conditions = report["counts"]["condition_names"]
    families = report["counts"]["families"]
    provenance = report["provenance"]
    counts = report["counts"]

    family_lookup = {
        (row["detector"], row["condition"], row["family"]): row
        for row in report["by_generator_family"]
    }
    agg_lookup = {
        (row["detector"], row["condition"]): row
        for row in report["aggregate_conditions"]
    }
    color_map = {
        fam: FAMILY_COLORS.get(fam, FALLBACK_PALETTE[idx % len(FALLBACK_PALETTE)])
        for idx, fam in enumerate(families)
    }

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelcolor": "#273745",
        "text.color": "#273745",
        "axes.titleweight": "semibold",
        "figure.facecolor": "white",
    })

    x = np.arange(len(conditions))
    bar_width = 0.34
    offset = 0.19
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.6), sharex=True)

    for axis, (detector, detector_label) in zip(axes, DETECTORS):
        fn_bottom = np.zeros(len(conditions), dtype=float)
        fp_bottom = np.zeros(len(conditions), dtype=float)

        for fam in families:
            color = color_map[fam]
            fn_vals = np.array([family_lookup[(detector, c, fam)]["fn"] for c in conditions], dtype=float)
            fp_vals = np.array([family_lookup[(detector, c, fam)]["fp"] for c in conditions], dtype=float)

            axis.bar(
                x - offset, fn_vals, width=bar_width, bottom=fn_bottom,
                color=color, edgecolor="white", linewidth=0.6,
            )
            axis.bar(
                x + offset, fp_vals, width=bar_width, bottom=fp_bottom,
                color=color, edgecolor="#1f2937", linewidth=0.6, hatch="///", alpha=0.82,
            )
            for idx in range(len(conditions)):
                if fn_vals[idx] >= 2:
                    axis.text(
                        x[idx] - offset, fn_bottom[idx] + fn_vals[idx] / 2,
                        f"{int(fn_vals[idx])}", ha="center", va="center",
                        fontsize=7.5, color="white", fontweight="semibold",
                    )
                if fp_vals[idx] >= 2:
                    axis.text(
                        x[idx] + offset, fp_bottom[idx] + fp_vals[idx] / 2,
                        f"{int(fp_vals[idx])}", ha="center", va="center",
                        fontsize=7.5, color="white", fontweight="semibold",
                    )
            fn_bottom += fn_vals
            fp_bottom += fp_vals

        ymax = max(12.0, float(max(fn_bottom.max(), fp_bottom.max())) * 1.24)
        axis.set_ylim(0, ymax)
        for idx, cond in enumerate(conditions):
            agg = agg_lookup[(detector, cond)]
            axis.text(
                x[idx] - offset, fn_bottom[idx] + ymax * 0.025,
                f"FN:{int(agg['fn'])}", ha="center", va="bottom",
                fontsize=7.5, color="#1f2937", fontweight="semibold",
            )
            axis.text(
                x[idx] + offset, fp_bottom[idx] + ymax * 0.025,
                f"FP:{int(agg['fp'])}", ha="center", va="bottom",
                fontsize=7.5, color="#475569",
            )

        axis.set_title(detector_label, loc="left", fontsize=11.5, pad=8)
        axis.set_ylabel("Threshold misses (count)")
        axis.grid(axis="y", alpha=0.18)
        axis.set_axisbelow(True)

    family_handles = [
        Patch(facecolor=color_map[fam], edgecolor="white", label=FAMILY_LABELS.get(fam, fam))
        for fam in families
    ]
    kind_handles = [
        Patch(facecolor="#64748b", edgecolor="white", label="Left bar (solid): FN (generated missed)"),
        Patch(facecolor="#cbd5e1", edgecolor="#1f2937", hatch="///", label="Right bar (hatched): FP (matched real flagged)"),
    ]
    axes[0].legend(
        handles=family_handles + kind_handles,
        loc="upper left", bbox_to_anchor=(0.0, 1.25), ncol=3, frameon=False, fontsize=8.8,
    )
    axes[-1].set_xticks(x, [PLOT_CONDITION_LABELS.get(c, c) for c in conditions], fontsize=8.5)

    fig.suptitle(
        "Held-out threshold errors by generator family and processing condition",
        x=0.07, y=0.97, ha="left", fontsize=15.5,
    )
    caption = (
        f"Split: {provenance['split']} · {counts['sources_in_split']} images "
        f"({counts['matched_groups']} matched groups) · "
        f"decision: score > {provenance['threshold']:g} (equality is negative) · "
        f"protocol {provenance['protocol_hash'][:12]}"
    )
    fig.text(0.07, 0.02, caption, fontsize=8.6, color="#475569")
    fig.subplots_adjust(left=0.07, right=0.98, top=0.84, bottom=0.13, hspace=0.25)

    written: list[Path] = []
    for ext in ("png", "pdf"):
        out_path = output_dir / f"{stem}.{ext}"
        save_kwargs: dict[str, Any] = {"dpi": 190, "bbox_inches": "tight"}
        if ext == "pdf":
            save_kwargs["metadata"] = {
                "Title": "Held-out threshold errors by generator family",
                "Creator": "scripts/analyze_generator_errors.py",
                "CreationDate": None,
            }
        fig.savefig(out_path, **save_kwargs)
        written.append(out_path)
    plt.close(fig)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path, nargs="?", default=Path("output/benchmark"))
    parser.add_argument("--split", choices=SPLITS, default="test")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--aggregate-csv-out", type=Path)
    parser.add_argument("--figure-dir", type=Path)
    args = parser.parse_args(argv)

    try:
        report = analyze_study(args.study, split=args.split)
        json_out = args.json_out or (args.study / "generator-error-analysis.json")
        csv_out = args.csv_out or (args.study / "generator-error-analysis.csv")
        agg_csv_out = args.aggregate_csv_out or (args.study / "condition-calibration-summary.csv")
        figure_dir = args.figure_dir or (args.study / "figures")

        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        _write_csv(csv_out, FAMILY_CSV_FIELDS, report["by_generator_family"], report["provenance"])
        _write_csv(agg_csv_out, AGGREGATE_CSV_FIELDS, report["aggregate_conditions"], report["provenance"])
        figures = render_figure(report, figure_dir)

        print(json.dumps({
            "json": str(json_out),
            "family_csv": str(csv_out),
            "aggregate_csv": str(agg_csv_out),
            "figures": [str(path) for path in figures],
            "protocol_hash": report["provenance"]["protocol_hash"],
            "split": report["provenance"]["split"],
            "matched_groups": report["counts"]["matched_groups"],
        }, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
