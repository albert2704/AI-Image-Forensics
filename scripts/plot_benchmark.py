#!/usr/bin/env python3
"""Render standalone figures from completed measured benchmark journals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np


LABELS = {
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
COLORS = {"bfree": "#1967a3", "frequency": "#a04968"}
NAMES = {"bfree": "B-Free", "frequency": "FFT/DCT + logistic regression"}


def _save(figure, output, stem):
    for extension in ("png", "pdf"):
        figure.savefig(output / f"{stem}.{extension}", dpi=190, bbox_inches="tight")
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.study / "figures"
    output.mkdir(parents=True, exist_ok=True)
    protocol = json.loads((args.study / "protocol.json").read_text())
    conditions = [condition["name"] for condition in protocol["conditions"]]
    summary, predictions = {}, {}
    for detector in NAMES:
        directory = args.study / "results" / detector
        raw = json.loads((directory / "summary.json").read_text())
        if raw["protocol_hash"] != protocol["protocol_hash"]:
            raise ValueError("Summary protocol identity does not match.")
        summary[detector] = raw["splits"]["test"]
        if not summary[detector]["coverage"]["complete"]:
            raise ValueError(f"{detector} test predictions are incomplete; final figures were not rendered.")
        predictions[detector] = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
        predictions[detector] = [row for row in predictions[detector] if row["split"] == "test"]
    coverage = summary["bfree"]["coverage"]
    caption = f"{coverage['expected_sources']} held-out project test images / {coverage['expected_groups']} matched groups · fixed threshold > {protocol['threshold']:g}"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.labelcolor": "#273745", "text.color": "#273745",
                         "axes.titleweight": "semibold", "figure.facecolor": "white"})
    x = np.arange(len(conditions))
    figure, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    for axis, metric, title in zip(axes, ("balanced_accuracy", "auroc"), ("Balanced accuracy at the frozen threshold", "Ranking performance (AUROC)")):
        for index, detector in enumerate(NAMES):
            values = [summary[detector]["conditions"][condition]["metrics"][metric] for condition in conditions]
            if any(value is None for value in values):
                raise ValueError("A required plot metric is undefined.")
            axis.bar(x + (index - .5) * .36, values, width=.34, color=COLORS[detector], label=NAMES[detector])
        axis.axhline(.5, color="#85939e", linewidth=.8, linestyle="--")
        axis.set_ylim(0, 1.05)
        axis.set_ylabel(title)
        axis.set_yticks(np.linspace(0, 1, 6))
        axis.grid(axis="y", alpha=.18)
        axis.set_axisbelow(True)
    axes[0].legend(loc="lower right", bbox_to_anchor=(1, 1.01), ncol=2, frameon=False)
    axes[-1].set_xticks(x, [LABELS.get(condition, condition) for condition in conditions], fontsize=8)
    figure.suptitle("Detection under repeated compression and resizing", x=.08, ha="left", fontsize=17)
    figure.text(.08, .025, caption + "\nPoint estimates on delivered Synthbuster/RAISE releases; class processing histories differ.", fontsize=9)
    figure.subplots_adjust(top=.91, bottom=.17, left=.08, hspace=.12)
    _save(figure, output, "detector_robustness")

    comparisons = [condition for condition in conditions if condition != "baseline"]
    figure, axis = plt.subplots(figsize=(10, 7))
    for index, detector in enumerate(NAMES):
        for position, condition in enumerate(comparisons):
            paired = summary[detector]["paired_vs_baseline"][condition]
            delta, interval = paired["balanced_accuracy_delta"], paired["balanced_accuracy_delta_ci95"]
            if delta is None or interval is None:
                raise ValueError("A paired interval is unavailable; final interval figure was not rendered.")
            y = position + (index - .5) * .24
            axis.plot([interval[0] * 100, interval[1] * 100], [y, y], color=COLORS[detector], linewidth=1.8)
            axis.scatter([delta * 100], [y], color=COLORS[detector], s=36, label=NAMES[detector] if position == 0 else None, zorder=3)
    axis.axvline(0, color="#52636f", linewidth=1, linestyle="--")
    axis.set_yticks(np.arange(len(comparisons)), [LABELS.get(condition, condition).replace("\n", ", ") for condition in comparisons])
    axis.invert_yaxis()
    axis.set_xlabel("Balanced accuracy change from baseline (percentage points)")
    axis.set_title("Paired changes with 95% group bootstrap intervals", loc="left", fontsize=15)
    axis.legend(loc="best", frameon=False)
    axis.grid(axis="x", alpha=.18)
    figure.text(.02, .015, f"{protocol['bootstrap_samples']:,} resamples of matched source groups; seed {protocol['seed']}. Pointwise intervals, not simultaneous bounds.", fontsize=9)
    figure.tight_layout(rect=(0, .04, 1, 1))
    _save(figure, output, "paired_balanced_accuracy_changes")

    figure, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    class_colors = {0: "#2e846d", 1: "#bc6952"}
    for axis, detector in zip(axes, NAMES):
        for label in (0, 1):
            samples = [[row["score"] for row in predictions[detector] if row["condition"] == condition and row["label"] == label] for condition in conditions]
            boxes = axis.boxplot(samples, positions=x + (label - .5) * .34, widths=.26, patch_artist=True,
                                 manage_ticks=False, showfliers=True,
                                 flierprops={"marker": ".", "markersize": 3, "alpha": .55,
                                             "markerfacecolor": class_colors[label], "markeredgecolor": "none"},
                                 medianprops={"color": "white", "linewidth": 1.4},
                                 whiskerprops={"color": class_colors[label]}, capprops={"color": class_colors[label]})
            for box in boxes["boxes"]:
                box.set_facecolor(class_colors[label])
                box.set_edgecolor(class_colors[label])
        axis.axhline(protocol["threshold"], color="#52636f", linestyle="--", linewidth=.9)
        axis.set_ylim(-.03, 1.03)
        axis.set_title(NAMES[detector], loc="left")
        axis.set_ylabel("Bounded model score")
        axis.grid(axis="y", alpha=.18)
    axes[0].legend(handles=[Patch(color=class_colors[0], label="Real"), Patch(color=class_colors[1], label="Generated")],
                   loc="lower right", bbox_to_anchor=(1, 1.01), ncol=2, frameon=False)
    axes[-1].set_xticks(x, [LABELS.get(condition, condition) for condition in conditions], fontsize=8)
    figure.suptitle("Score distributions by condition and ground-truth class", x=.08, ha="left", fontsize=16)
    figure.text(.08, .025, caption + "\nBoxes: interquartile range and median; whiskers: 1.5×IQR; points beyond whiskers are shown. Scores are not calibrated origin probabilities.", fontsize=8)
    figure.subplots_adjust(left=.08, right=.98, top=.89, bottom=.17, hspace=.2)
    _save(figure, output, "score_distributions")
    print(json.dumps({"output_directory": str(output), "figures": ["detector_robustness", "paired_balanced_accuracy_changes", "score_distributions"]}, indent=2))


if __name__ == "__main__":
    main()
