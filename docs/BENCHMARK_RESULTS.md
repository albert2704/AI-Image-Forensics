# Measured benchmark results

These are actual outputs from the frozen 320-image Synthbuster/RAISE pilot. The test images were held out from this project's training and policy choices. They are not claimed to be unseen throughout upstream B-Free development.

Protocol hash: `1c974e78ed2d391de1cd1897ac2513c757b2016917d621e3f38c97362ef5aafa`. Manifest hash: `fdaae67c8593aa126e69fd9da0b9e11ff5542fd89ac42ca4fe36c326ab038ca5`.

## Coverage and frozen choices

The study contains 160 matched source groups, split into 64 training images, 64 validation images and 192 test images (96 test groups). Each test group contains one real reference and one generated image. Every detector completed all nine conditions, producing 1,728 test predictions. The validation split was not scored or used to select settings.

Both models use the fixed decision `score > 0.5`. Primary contrast: three cumulative JPEG Q85 encodes versus baseline. The 5,000-draw percentile bootstrap resamples matched source groups, retaining both members and their paired predictions; seed 20261018. Intervals are pointwise and do not include model-training uncertainty.

B-Free ran on `mps` with checkpoint SHA-256 `5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947`. The FFT/DCT comparator standardized and fitted 79 features using only 64 training originals, with fixed L2 coefficient 0.01. Its optimizer converged in 7 updates; no validation or test tuning occurred.

| Detector | Test predictions | Failed attempts across requested splits | Cached prediction rows across requested splits |
|---|---:|---:|---:|
| B-Free | 1,728 | 0 | 0 |
| FFT/DCT + logistic regression | 1,728 | 0 | 0 |

## Held out discrimination

AUROC is a ranking metric. Balanced accuracy is measured at the frozen threshold. All rows use the same 96 real and 96 generated test images.

| Condition | B-Free balanced accuracy | B-Free AUROC | Frequency balanced accuracy | Frequency AUROC |
|---|---:|---:|---:|---:|
| Baseline | 100.00% | 1.0000 | 73.44% | 0.8040 |
| JPEG Q85, round 1 | 100.00% | 1.0000 | 73.44% | 0.8021 |
| JPEG Q85, round 3 | 100.00% | 1.0000 | 73.44% | 0.8010 |
| Resize ×0.9, round 1 | 99.48% | 0.9998 | 73.44% | 0.8028 |
| Resize ×0.9, round 3 | 95.83% | 0.9962 | 72.92% | 0.8043 |
| Resize → JPEG Q95, round 1 | 99.48% | 0.9998 | 72.92% | 0.8023 |
| Resize → JPEG Q95, round 3 | 95.83% | 0.9965 | 72.92% | 0.8031 |
| JPEG Q95 → resize, round 3 | 94.79% | 0.9966 | 72.92% | 0.8027 |
| Single pass at round 3 size, Q95 | 96.88% | 0.9967 | 72.40% | 0.8022 |

## Primary paired contrast

| Detector | Baseline balanced accuracy | Q85 round 3 balanced accuracy | Change, percentage points | 95% group bootstrap interval, percentage points | Paired groups |
|---|---:|---:|---:|---:|---:|
| B-Free | 100.00% | 100.00% | +0.00 | [+0.00, +0.00] | 96 |
| FFT/DCT + logistic regression | 73.44% | 73.44% | +0.00 | [+0.00, +0.00] | 96 |

B-Free had no threshold decision changes in this primary contrast. Its degenerate [0, 0] bootstrap interval follows from resampling an observed sample with no decision changes; it does not establish that the population effect must be zero. Mean absolute score change was 0.012009, so decision stability is distinct from an unchanged score.

FFT/DCT + logistic regression had no threshold decision changes in this primary contrast. Its degenerate [0, 0] bootstrap interval follows from resampling an observed sample with no decision changes; it does not establish that the population effect must be zero. Mean absolute score change was 0.004142, so decision stability is distinct from an unchanged score.

The primary contrast includes both introducing JPEG compression and repeating it. The one-round JPEG arm provides the control for distinguishing the first encode from later encodes. Likewise, cumulative resizing changes both final dimensions and processing history; the single-pass combined arm controls final dimensions when comparing its history with three cumulative combined rounds.

Score persistence measures response stability under these interventions. It does not establish whether an individual image is authentic. The intervals describe sampling variation across these matched groups; they are not individual authenticity probabilities.

## Calibration and operating errors

These summaries assess the supplied bounded scores. Neither detector was independently calibrated on this study.

| Detector / condition | TPR | FPR | Brier | NLL | ECE |
|---|---:|---:|---:|---:|---:|
| B-Free, Baseline | 100.00% | 0.00% | 0.0018 | 0.0201 | 0.0191 |
| B-Free, JPEG Q85, round 3 | 100.00% | 0.00% | 0.0031 | 0.0274 | 0.0256 |
| FFT/DCT + logistic regression, Baseline | 76.04% | 29.17% | 0.1872 | 0.6322 | 0.1100 |
| FFT/DCT + logistic regression, JPEG Q85, round 3 | 76.04% | 29.17% | 0.1890 | 0.6363 | 0.1184 |

The frequency model's apparent baseline training balanced accuracy is 92.19%, with AUROC 0.9873 on 64 fitting images. This is a fit diagnostic, not additional held out evidence.

## Matched generator strata

Each row below uses that generator's 24 test images plus its 24 distinct matched real references (24 groups), not all 96 pooled real images. These small subgroup results are descriptive; no unseen generator evaluation or multiple comparison claim is made.

| Generator | B-Free baseline bAcc | B-Free Q85 round 3 bAcc | Frequency baseline bAcc | Frequency Q85 round 3 bAcc |
|---|---:|---:|---:|---:|
| dalle3 | 100.00% | 100.00% | 64.58% | 64.58% |
| firefly | 100.00% | 100.00% | 72.92% | 72.92% |
| midjourney-v5 | 100.00% | 100.00% | 81.25% | 81.25% |
| stable-diffusion-xl | 100.00% | 100.00% | 75.00% | 75.00% |

The real release was already resized by its provider, while released synthetic dimensions and histories differ. Firefly inputs are approximately 4 megapixels, versus approximately 1 megapixel for the real reference release. The fixed 256 × 256 frequency preprocessing also changes aspect ratio. Content matching does not remove these acquisition and preprocessing confounds. Performance differences cannot be attributed solely to generator traces, and the pilot does not establish general performance on new generators, camera sources or social media images.

## Reproduction artifacts

- `output/benchmark/protocol.json`: frozen data, model, code and analysis identity.
- `output/benchmark/frequency-model.json`: fitted training-only comparator and convergence record.
- `output/benchmark/results/{bfree,frequency}/predictions.jsonl`: append-only measured prediction provenance.
- `output/benchmark/results/{bfree,frequency}/predictions.csv`: evaluator-compatible derived rows.
- `output/benchmark/results/{bfree,frequency}/summary.json`: full metrics, ECE bins, paired group intervals and coverage.
- `output/benchmark/consolidation.json`: byte-preserving worker consolidation, journal checksums and cross-detector transformation audit.
- `output/benchmark/generator-subgroups.json`: exact matched-family subgroup metrics and primary group intervals.
- `output/benchmark/figures/detector_robustness.{png,pdf}`: balanced accuracy and AUROC by condition.
- `output/benchmark/figures/paired_balanced_accuracy_changes.{png,pdf}`: paired change intervals.
- `output/benchmark/figures/score_distributions.{png,pdf}`: real/generated score distributions.

Generate these tables with `python scripts/summarize_benchmark_results.py output/benchmark` and figures with `python scripts/plot_benchmark.py output/benchmark`. The scripts refuse incomplete test summaries. Agent tool selection and reporting accuracy are evaluated separately; these detector results do not establish an adaptive agent benefit.

B-Free ran concurrently with the frequency comparator in an isolated worker directory under an exact byte-copy of the frozen protocol. After completion, its result files and content-addressed cache were copied into the canonical study directory without changing journal rows. The original worker output remains available; checksums and cross-detector transformation checks are recorded in `output/benchmark/consolidation.json`.

An independent implementation verified every condition's held out AUROC, balanced accuracy and confusion matrix against scikit-learn within 1e-12, and independently reconstructed the primary paired group bootstrap. Exact journals, source identities and model provenance also passed. The machine readable record is `output/verification/independent-metric-check.json`.
