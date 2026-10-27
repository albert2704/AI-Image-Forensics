"""Study 2: where does a detector's decision break under single-pass resizing and JPEG?

This module only defines a new condition grid and analyses its results. Freezing,
rendering, scoring, journals and caching are delegated unchanged to the frozen
benchmark runner, so study 2 lives in its own protocol and output directory and
never edits the pilot. Missing or failed predictions stay missing.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from . import benchmark

STUDY_NAME = "Study 2: break-point grid of single-pass resizing and JPEG"
DEFAULT_OUTPUT = Path("output/breakpoint-study")
# Prespecified before scoring; see docs/BREAKPOINT_PROTOCOL.md.
GRID_SCALES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)
GRID_QUALITIES = (None, 95, 85, 75, 65, 50)  # None = lossless PNG, no JPEG encode
PRIMARY_CONDITION = "s0.50_png"
SEED = 20261018
BOOTSTRAP_SAMPLES = 5000


def cell_name(scale: float, quality: int | None) -> str:
    if scale == 1.0 and quality is None:
        return "baseline"
    return f"s{scale:.2f}_{'png' if quality is None else f'q{quality}'}"


def grid_conditions():
    """Every cell is one pass from the original: resize to the target, then encode once."""
    conditions = [{"name": "baseline", "operation": "combined", "quality": 95, "scale": .9, "rounds": 0,
                   "mode": "cumulative", "order": "resize-jpeg"}]
    for quality in GRID_QUALITIES:
        for scale in GRID_SCALES:
            if scale == 1.0 and quality is None:
                continue
            operation = "resize" if quality is None else "jpeg" if scale == 1.0 else "combined"
            conditions.append({"name": cell_name(scale, quality), "operation": operation,
                               "quality": 95 if quality is None else quality, "scale": scale, "rounds": 1,
                               "mode": "independent", "order": "resize-jpeg"})
    return conditions


def freeze(manifest_path, output_dir, detector):
    if not detector.available:
        raise ValueError(detector.reason)
    return benchmark.freeze_protocol(manifest_path, output_dir, {
        "study_name": STUDY_NAME, "conditions": grid_conditions(), "threshold": .5,
        "seed": SEED, "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bfree_fingerprint": benchmark.detector_fingerprint(detector)})


def _rate(values):
    return sum(values) / len(values) if values else None


def _cells(protocol):
    by_name = {}
    for quality in GRID_QUALITIES:
        for scale in GRID_SCALES:
            by_name[cell_name(scale, quality)] = (scale, quality)
    names = {condition["name"] for condition in protocol["conditions"]}
    if names != set(by_name):
        raise ValueError("This protocol does not contain the study 2 grid.")
    return by_name


def analyze(protocol_path, detector_id="bfree", split="test"):
    """Grid metrics, per-source break points and survival curves from recorded predictions only."""
    protocol_path = Path(protocol_path).resolve()
    protocol = benchmark.load_protocol(protocol_path)
    cells = _cells(protocol)
    threshold = protocol["threshold"]
    directory = protocol_path.parent / "results" / detector_id
    rows = [row for row in benchmark._read_journal(directory / "predictions.jsonl") if row["split"] == split]
    expected = [source for source in protocol["sources"] if source["split"] == split]
    scores = defaultdict(dict)
    meta = {source["source_id"]: source for source in expected}
    for row in rows:
        scores[row["source_id"]][row["condition"]] = row["score"]
    complete = [source_id for source_id in meta if len(scores[source_id]) == len(cells)]
    complete_set = set(complete)
    paired_rows = [row for row in rows if row["source_id"] in complete_set]

    def elevated(value):
        return value > threshold

    grid = []
    for name, (scale, quality) in cells.items():
        real = [elevated(scores[s][name]) for s in complete if meta[s]["label"] == 0]
        fake = [elevated(scores[s][name]) for s in complete if meta[s]["label"] == 1]
        flips = [elevated(scores[s][name]) != elevated(scores[s]["baseline"]) for s in complete]
        tpr, fpr = _rate(fake), _rate(real)
        interval = None if name == "baseline" else benchmark.grouped_paired_interval(
            paired_rows, name, threshold,
            protocol["bootstrap_samples"], protocol["seed"])
        grid.append({"condition": name, "scale": scale, "quality": quality or "png",
                     "sources": len(complete), "tpr": tpr, "fpr": fpr,
                     "balanced_accuracy": None if tpr is None or fpr is None else .5 * (tpr + 1 - fpr),
                     "decision_change_rate": _rate(flips),
                     "balanced_accuracy_delta_ci95": interval and interval["ci95"],
                     "bootstrap_reason": interval and interval["reason"]})

    # A source's break point on one quality row is the gentlest scale whose decision differs from its original.
    breakpoints, nonmonotone = [], defaultdict(int)
    for source_id in complete:
        baseline = elevated(scores[source_id]["baseline"])
        record = {"source_id": source_id, "label": meta[source_id]["label"], "generator": meta[source_id]["generator"],
                  "group_id": meta[source_id]["group_id"], "baseline_score": scores[source_id]["baseline"]}
        for quality in GRID_QUALITIES:
            changed = [elevated(scores[source_id][cell_name(scale, quality)]) != baseline for scale in GRID_SCALES]
            first = next((GRID_SCALES[i] for i, value in enumerate(changed) if value), None)
            record[f"break_scale_{quality or 'png'}"] = first
            # Recorded, not assumed: does the decision stay changed at every smaller scale?
            if first is not None and not all(changed[GRID_SCALES.index(first):]):
                nonmonotone[str(quality or "png")] += 1
        breakpoints.append(record)

    survival = {}
    for quality in GRID_QUALITIES:
        row_name = str(quality or "png")
        survival[row_name] = [{"scale": scale,
                               "generated_still_elevated": _rate([elevated(scores[s][cell_name(scale, quality)]) for s in complete if meta[s]["label"] == 1]),
                               "real_still_not_elevated": _rate([not elevated(scores[s][cell_name(scale, quality)]) for s in complete if meta[s]["label"] == 0])}
                              for scale in GRID_SCALES]

    primary = next(cell for cell in grid if cell["condition"] == PRIMARY_CONDITION)
    summary = {"protocol_hash": protocol["protocol_hash"], "study_name": protocol["study_name"], "detector_id": detector_id,
               "split": split, "threshold_rule": f"score > {threshold}",
               "coverage": {"expected_sources": len(expected), "complete_sources": len(complete),
                            "predictions": len(rows), "expected_predictions": len(expected) * len(cells),
                            "complete": len(complete) == len(expected)},
               "primary_contrast": {"condition": PRIMARY_CONDITION, "versus": "baseline", **primary},
               "grid": grid, "survival": survival, "nonmonotone_break_counts": dict(nonmonotone),
               "cautions": ["Each cell is one pass from the original; cumulative histories are covered by the pilot.",
                            "Scale is relative to each released original, whose resolution differs between real and generated sources.",
                            "Hypotheses were motivated by pilot results on the same test images; treat the grid as descriptive.",
                            "Intervals resample matched groups and do not describe individual image authenticity."]}
    out = protocol_path.parent / "analysis" / detector_id
    out.mkdir(parents=True, exist_ok=True)
    benchmark._atomic_json(out / "breakpoint-summary.json", summary)
    with (out / "grid.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(grid[0]))
        writer.writeheader()
        writer.writerows({**cell, "balanced_accuracy_delta_ci95": json.dumps(cell["balanced_accuracy_delta_ci95"])} for cell in grid)
    with (out / "breakpoints.csv").open("w", newline="", encoding="utf-8") as stream:
        if breakpoints:
            writer = csv.DictWriter(stream, fieldnames=list(breakpoints[0]))
            writer.writeheader()
            writer.writerows(breakpoints)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze_cmd = commands.add_parser("freeze", help="Freeze the study 2 grid before any scoring")
    freeze_cmd.add_argument("manifest", type=Path)
    freeze_cmd.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run_cmd = commands.add_parser("run", help="Score the frozen grid; resumable")
    run_cmd.add_argument("protocol", type=Path)
    run_cmd.add_argument("--max-new-scores", type=int)
    run_cmd.add_argument("--retry-failures", action="store_true")
    analyze_cmd = commands.add_parser("analyze", help="Derive grid metrics and break points from recorded predictions")
    analyze_cmd.add_argument("protocol", type=Path)
    args = parser.parse_args(argv)
    try:
        from .detectors import choose_detector
        if args.command == "freeze":
            frozen = freeze(args.manifest, args.output, choose_detector({}))
            result = {"protocol_path": str(args.output / "protocol.json"), "protocol_hash": frozen["protocol_hash"],
                      "conditions": len(frozen["conditions"]), "sources": len(frozen["sources"])}
        elif args.command == "run":
            result = benchmark.run_benchmark(args.protocol, choose_detector({}), ["test"], args.max_new_scores, "bfree", args.retry_failures)
        else:
            summary = analyze(args.protocol)
            result = {"coverage": summary["coverage"], "primary_contrast": summary["primary_contrast"]}
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
