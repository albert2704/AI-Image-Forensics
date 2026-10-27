#!/usr/bin/env python3
"""Write measured benchmark tables and matched-generator summaries after completion."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forensics.benchmark import grouped_paired_interval, load_protocol
from forensics.evaluation import evaluate_rows


TITLES = {
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
MODELS = {"bfree": "B-Free", "frequency": "FFT/DCT + logistic regression"}


def percent(value):
    return "undefined" if value is None else f"{100 * value:.2f}%"


def change(value):
    return "undefined" if value is None else f"{100 * value:+.2f}"


def interval(value):
    return "undefined" if value is None else f"[{100 * value[0]:+.2f}, {100 * value[1]:+.2f}]"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--document", type=Path, default=Path("docs/BENCHMARK_RESULTS.md"))
    args = parser.parse_args()
    protocol = load_protocol(args.study / "protocol.json")
    sources = {row["source_id"]: row for row in protocol["sources"]}
    summary, journals = {}, {}
    for model in MODELS:
        directory = args.study / "results" / model
        summary[model] = json.loads((directory / "summary.json").read_text())
        if summary[model]["protocol_hash"] != protocol["protocol_hash"] or not summary[model]["splits"]["test"]["coverage"]["complete"]:
            raise ValueError("Both models must have complete test results under this exact protocol.")
        journals[model] = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
    family_by_group = {}
    for row in protocol["sources"]:
        if row["label"] == 1:
            family_by_group[row["group_id"]] = row["generator"]
    subgroups = {"protocol_hash": protocol["protocol_hash"], "scope": "Each generator plus its distinct matched real references; test split only", "models": {}}
    for model in MODELS:
        subgroups["models"][model] = {}
        for family in sorted(set(family_by_group.values())):
            selected = [row for row in journals[model] if row["split"] == "test" and family_by_group[row["group_id"]] == family]
            result = evaluate_rows(selected, threshold=protocol["threshold"], bootstrap_samples=0, seed=protocol["seed"])
            primary = grouped_paired_interval(selected, "jpeg_q85_r3", protocol["threshold"], protocol["bootstrap_samples"], protocol["seed"])
            pair = result["paired_vs_baseline"]["jpeg_q85_r3"]
            pair["balanced_accuracy_delta_ci95"], pair["bootstrap"], pair["reason"] = primary["ci95"], primary, primary["reason"]
            result["matched_groups"] = len({row["group_id"] for row in selected})
            subgroups["models"][model][family] = result
    (args.study / "generator-subgroups.json").write_text(json.dumps(subgroups, indent=2, allow_nan=False) + "\n")
    coverage = summary["bfree"]["splits"]["test"]["coverage"]
    train_model = json.loads((args.study / "frequency-model.json").read_text())
    bfree_meta = json.loads((args.study / "results" / "bfree" / "model.json").read_text())
    text = ["# Measured benchmark results", "",
            "These are actual outputs from the frozen 320-image Synthbuster/RAISE pilot. The test images were held out from this project's training and policy choices. They are not claimed to be unseen throughout upstream B-Free development.", "",
            f"Protocol hash: `{protocol['protocol_hash']}`. Manifest hash: `{protocol['manifest_sha256']}`.", "",
            "## Coverage and frozen choices", "",
            f"The study contains 160 matched source groups, split into 64 training images, 64 validation images and {coverage['expected_sources']} test images ({coverage['expected_groups']} test groups). Each test group contains one real reference and one generated image. Every detector completed all nine conditions, producing {coverage['actual_predictions']:,} test predictions. The validation split was not scored or used to select settings.", "",
            f"Both models use the fixed decision `score > {protocol['threshold']:g}`. Primary contrast: three cumulative JPEG Q85 encodes versus baseline. The {protocol['bootstrap_samples']:,}-draw percentile bootstrap resamples matched source groups, retaining both members and their paired predictions; seed {protocol['seed']}. Intervals are pointwise and do not include model-training uncertainty.", "",
            f"B-Free ran on `{bfree_meta.get('device', 'unknown')}` with checkpoint SHA-256 `{bfree_meta['checkpoint_sha256']}`. The FFT/DCT comparator standardized and fitted 79 features using only {len(train_model['training_source_ids'])} training originals, with fixed L2 coefficient 0.01. Its optimizer converged in {train_model['training_diagnostics']['iterations']} updates; no validation or test tuning occurred.", "",
            "| Detector | Test predictions | Failed attempts across requested splits | Cached prediction rows across requested splits |",
            "|---|---:|---:|---:|"]
    for model, name in MODELS.items():
        test = summary[model]["splits"]["test"]
        text.append(f"| {name} | {test['coverage']['actual_predictions']:,} | {summary[model]['failure_attempts']} | {sum(row.get('score_origin') == 'cache' for row in journals[model])} |")
    text += ["", "## Held out discrimination", "",
             "AUROC is a ranking metric. Balanced accuracy is measured at the frozen threshold. All rows use the same 96 real and 96 generated test images.", "",
             "| Condition | B-Free balanced accuracy | B-Free AUROC | Frequency balanced accuracy | Frequency AUROC |",
             "|---|---:|---:|---:|---:|"]
    for condition in protocol["conditions"]:
        name = condition["name"]
        b = summary["bfree"]["splits"]["test"]["conditions"][name]["metrics"]
        f = summary["frequency"]["splits"]["test"]["conditions"][name]["metrics"]
        text.append(f"| {TITLES.get(name, name)} | {percent(b['balanced_accuracy'])} | {b['auroc']:.4f} | {percent(f['balanced_accuracy'])} | {f['auroc']:.4f} |")
    text += ["", "## Primary paired contrast", "",
             "| Detector | Baseline balanced accuracy | Q85 round 3 balanced accuracy | Change, percentage points | 95% group bootstrap interval, percentage points | Paired groups |",
             "|---|---:|---:|---:|---:|---:|"]
    for model, name in MODELS.items():
        primary = summary[model]["splits"]["test"]["paired_vs_baseline"]["jpeg_q85_r3"]
        text.append(f"| {name} | {percent(primary['baseline_balanced_accuracy_on_pairs'])} | {percent(primary['condition_balanced_accuracy_on_pairs'])} | {change(primary['balanced_accuracy_delta'])} | {interval(primary['balanced_accuracy_delta_ci95'])} | {primary['bootstrap']['paired_groups']} |")
    for model, name in MODELS.items():
        primary = summary[model]["splits"]["test"]["paired_vs_baseline"]["jpeg_q85_r3"]
        if primary["label_flip_rate"] == 0 and primary["balanced_accuracy_delta_ci95"] == [0.0, 0.0]:
            text += ["", f"{name} had no threshold decision changes in this primary contrast. Its degenerate [0, 0] bootstrap interval follows from resampling an observed sample with no decision changes; it does not establish that the population effect must be zero. Mean absolute score change was {primary['score_delta']['mean_absolute']:.6f}, so decision stability is distinct from an unchanged score."]
    text += ["", "The primary contrast includes both introducing JPEG compression and repeating it. The one-round JPEG arm provides the control for distinguishing the first encode from later encodes. Likewise, cumulative resizing changes both final dimensions and processing history; the single-pass combined arm controls final dimensions when comparing its history with three cumulative combined rounds.", "",
             "Score persistence measures response stability under these interventions. It does not establish whether an individual image is authentic. The intervals describe sampling variation across these matched groups; they are not individual authenticity probabilities.", "",
             "## Calibration and operating errors", "",
             "These summaries assess the supplied bounded scores. Neither detector was independently calibrated on this study.", "",
             "| Detector / condition | TPR | FPR | Brier | NLL | ECE |",
             "|---|---:|---:|---:|---:|---:|"]
    for model, name in MODELS.items():
        for condition in ("baseline", "jpeg_q85_r3"):
            values = summary[model]["splits"]["test"]["conditions"][condition]["metrics"]
            text.append(f"| {name}, {TITLES[condition]} | {percent(values['tpr'])} | {percent(values['fpr'])} | {values['brier']:.4f} | {values['nll']:.4f} | {values['ece']:.4f} |")
    train = summary["frequency"]["splits"]["train"]["conditions"].get("baseline")
    if train:
        values = train["metrics"]
        text += ["", f"The frequency model's apparent baseline training balanced accuracy is {percent(values['balanced_accuracy'])}, with AUROC {values['auroc']:.4f} on {train['counts']['sources']} fitting images. This is a fit diagnostic, not additional held out evidence."]
    text += ["", "## Matched generator strata", "",
             "Each row below uses that generator's 24 test images plus its 24 distinct matched real references (24 groups), not all 96 pooled real images. These small subgroup results are descriptive; no unseen generator evaluation or multiple comparison claim is made.", "",
             "| Generator | B-Free baseline bAcc | B-Free Q85 round 3 bAcc | Frequency baseline bAcc | Frequency Q85 round 3 bAcc |",
             "|---|---:|---:|---:|---:|"]
    for family in sorted(set(family_by_group.values())):
        values = []
        for model in MODELS:
            for condition in ("baseline", "jpeg_q85_r3"):
                values.append(percent(subgroups["models"][model][family]["conditions"][condition]["metrics"]["balanced_accuracy"]))
        text.append(f"| {family} | " + " | ".join(values) + " |")
    text += ["", "The real release was already resized by its provider, while released synthetic dimensions and histories differ. Firefly inputs are approximately 4 megapixels, versus approximately 1 megapixel for the real reference release. The fixed 256 × 256 frequency preprocessing also changes aspect ratio. Content matching does not remove these acquisition and preprocessing confounds. Performance differences cannot be attributed solely to generator traces, and the pilot does not establish general performance on new generators, camera sources or social media images.", "",
             "## Reproduction artifacts", "",
             "- `output/benchmark/protocol.json`: frozen data, model, code and analysis identity.",
             "- `output/benchmark/frequency-model.json`: fitted training-only comparator and convergence record.",
             "- `output/benchmark/results/{bfree,frequency}/predictions.jsonl`: append-only measured prediction provenance.",
             "- `output/benchmark/results/{bfree,frequency}/predictions.csv`: evaluator-compatible derived rows.",
             "- `output/benchmark/results/{bfree,frequency}/summary.json`: full metrics, ECE bins, paired group intervals and coverage.",
             "- `output/benchmark/consolidation.json`: byte-preserving worker consolidation, journal checksums and cross-detector transformation audit.",
             "- `output/benchmark/generator-subgroups.json`: exact matched-family subgroup metrics and primary group intervals.",
             "- `output/benchmark/figures/detector_robustness.{png,pdf}`: balanced accuracy and AUROC by condition.",
             "- `output/benchmark/figures/paired_balanced_accuracy_changes.{png,pdf}`: paired change intervals.",
             "- `output/benchmark/figures/score_distributions.{png,pdf}`: real/generated score distributions.", "",
             "Generate these tables with `python scripts/summarize_benchmark_results.py output/benchmark` and figures with `python scripts/plot_benchmark.py output/benchmark`. The scripts refuse incomplete test summaries. Agent tool selection and reporting accuracy are evaluated separately; these detector results do not establish an adaptive agent benefit.", ""]
    if (args.study / "consolidation.json").exists():
        text += ["B-Free ran concurrently with the frequency comparator in an isolated worker directory under an exact byte-copy of the frozen protocol. After completion, its result files and content-addressed cache were copied into the canonical study directory without changing journal rows. The original worker output remains available; checksums and cross-detector transformation checks are recorded in `output/benchmark/consolidation.json`.", ""]
    audit_path = args.study.parent / "verification" / "independent-metric-check.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text())
        if all(audit.get("detectors", {}).get(model, {}).get("status") == "passed" and
               audit["detectors"][model].get("journal_sha256") == hashlib.sha256((args.study / "results" / model / "predictions.jsonl").read_bytes()).hexdigest()
               for model in MODELS):
            text += ["An independent implementation verified every condition's held out AUROC, balanced accuracy and confusion matrix against scikit-learn within 1e-12, and independently reconstructed the primary paired group bootstrap. Exact journals, source identities and model provenance also passed. The machine readable record is `output/verification/independent-metric-check.json`.", ""]
    args.document.parent.mkdir(parents=True, exist_ok=True)
    args.document.write_text("\n".join(text), encoding="utf-8")
    print(json.dumps({"document": str(args.document), "subgroups": str(args.study / "generator-subgroups.json")}, indent=2))


if __name__ == "__main__":
    main()
