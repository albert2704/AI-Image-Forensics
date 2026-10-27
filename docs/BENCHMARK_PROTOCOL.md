# Frozen benchmark and frequency baseline

This is the execution protocol for the bounded dataset study. The earlier experiment protocol describes a broader research plan. The machine readable `protocol.json` created by this harness is the authority for an actual run: it freezes source files, splits, model identity, conditions, software and analysis settings **before any study detector scoring**. This is a local reproducibility record, not an externally registered study. Existing official demonstration images are excluded from the study.

## Dataset unit and separation

The acquisition plan contains 320 images: 160 real/generated source groups, with one real reference and one generated image in each group. Four generator strata contribute 40 groups each. Split by group, with 8/8/24 groups per stratum assigned to train/validation/test. This gives 64 training, 64 validation and 192 test images. The manifest, rather than these target counts, determines the final actual sample. Its `group_id` links the related real and generated image; a group cannot cross splits.

Required manifest columns are `source_id,path,label,generator,group_id,split,sha256,source_url`. Paths are relative to the manifest, labels are 0 for real and 1 for generated, and split values are exactly `train`, `validation` and `test`. `generator=real` identifies real sources; the optional `paired_generator` field retains their matched generator stratum. Additional acquisition metadata is preserved in the frozen source records. Each split must contain both labels. Source IDs must be unique, and duplicate normalized RGB pixels across IDs are rejected.

Each frozen source includes the input byte checksum, normalized pixel checksum, dimensions and explicit normalization notes. The harness uses the application's existing decoding procedure, including EXIF orientation, RGB conversion and white compositing for transparency. It also stores the original manifest checksum. A changed source, manifest, implementation or relevant runtime version prevents resuming that protocol. Related images remain paired; no duplicate source is treated as an independent sample.

The source releases have different processing histories. In particular, the chosen real release has already been resized by its provider, while generated source images retain their released dimensions and histories. This is a potential class confound for both B-Free and frequency features. Matched content does not eliminate it. Report source dimensions, formats and provenance by class, and limit findings to these releases. Do not describe a strong classifier score as proof of general generator detection. Synthbuster has been used in the B-Free research context: this test split is held out from this project's fitting and policy choices, not demonstrably unseen throughout upstream detector development. There is no held out generator family in this pilot. The acquisition record in `docs/DATASET.md` gives the concrete sources and limitations.

## Nine frozen conditions

All conditions use Pillow LANCZOS for resizing and JPEG 4:2:0 chroma subsampling, without progressive encoding or encoder optimization. Each cumulative round starts from the previous decoded result. At round `r`, target dimensions are `round(original dimension * 0.9**r)`. The single pass control reaches the same final dimensions directly from the original. The existing application transformation functions implement these operations.

| Condition ID | Transformation |
|---|---|
| `baseline` | Normalized original, without experimental processing |
| `jpeg_q85_r1` | One JPEG encode at quality 85 |
| `jpeg_q85_r3` | Three cumulative JPEG encodes at quality 85 |
| `resize_s0.9_r1` | One resize to 0.9 of the original dimensions |
| `resize_s0.9_r3` | Three cumulative resize operations, ending at 0.9³ |
| `combined_q95_s0.9_r1` | One resize then JPEG quality 95 |
| `combined_q95_s0.9_r3` | Three cumulative resize then JPEG quality 95 rounds |
| `reverse_q95_s0.9_r3` | Three cumulative JPEG quality 95 then resize rounds |
| `independent_q95_s0.9_r3` | One resize directly to 0.9³, then one JPEG quality 95 encode |

The reverse order arm ends in lossless PNG, avoiding an unintended final JPEG operation. Neural inputs are lossless PNG representations of each condition's decoded pixels. This preserves the intended JPEG artifacts without introducing another encode. Both the experimental artifact checksum and canonical RGB pixel checksum are recorded; the detector cache identifies pixels, not filenames or container bytes.

The primary endpoint is the change in balanced accuracy from baseline to `jpeg_q85_r3`. Other contrasts and metrics are secondary. Both classifiers use the frozen decision `score > 0.5`; equality predicts label 0. There is no threshold optimization, calibration fitting, hyperparameter selection or condition selection using validation or test outcomes. The validation split remains available for separately specified future work and must not be used to modify this already frozen study.

## B-Free and the independent frequency comparator

B-Free uses the installed official checkpoint and its native preprocessing. Before scoring, the harness records checkpoint bytes, upstream Python sources, model configuration, adapter code, library versions, model revision and device in a reproducible fingerprint. It passes a persistent detector object through the entire run so the checkpoint is not initialized for every image. A fingerprint mismatch prevents mixing results in a journal.

The independently implemented comparator uses 79 features followed by L2 logistic regression:

1. Normalize source pixels through the same application decoder, then resize each detector input to 256 × 256 using LANCZOS. This fixed feature preprocessing does not preserve aspect ratio and is explicitly different from B-Free's native preprocessing.
2. Compute luminance as `(0.299 R + 0.587 G + 0.114 B) / 255`.
3. Subtract mean luminance, compute an orthonormal 2D FFT, and average `log(1 + power)` in 16 radial frequency bins. Exclude the DC coefficient.
4. Divide luminance into 1,024 nonoverlapping 8 × 8 blocks. Compute orthonormal DCT-II coefficients and retain the mean absolute magnitude of each of the 63 AC coefficients.
5. Standardize features using the mean and population standard deviation of training originals only. Fit logistic regression with an unpenalized intercept and fixed L2 coefficient 0.01. A deterministic Newton solver uses backtracking, at most 100 updates and gradient infinity norm tolerance 1e-8. Failure to converge produces an error rather than a model.

Only the 64 training originals enter feature standardization and fitting; transformed variants, validation images and test images do not. Hyperparameters are fixed before fitting. The model file contains feature and optimizer specifications, scaler values, coefficients, intercept, convergence diagnostics, exact training source IDs and the protocol hash. It is created without overwriting an existing model. Evaluate all nine conditions on the test split so the comparator has the same robustness task as B-Free. Apparent training performance, if requested, is labeled separately and is not a generalization estimate.

This baseline is intentionally small enough to inspect. It may learn acquisition or compression differences and should not be presented as a new state of the art detector. Both classifiers return bounded sigmoid scores without a claim of independent probability calibration. Brier score, NLL and ECE measure their behavior on the specified data rather than guaranteeing calibration elsewhere.

## Resumption, caching and failure accounting

For each detector, successful predictions append to `results/<detector>/predictions.jsonl`; failures append separately to `failures.jsonl`. A successful source/condition is never appended twice. Repeating a run resumes missing predictions. Previously failed attempts are retried only with the explicit `--retry-failures` flag, and earlier failure records remain. A process lock prevents concurrent writers in the same study directory.

The score cache key contains canonical RGB pixels and dimensions, the complete model fingerprint and its preprocessing fingerprint. Identical pixels across conditions reuse a real measured score and are marked `score_origin=cache`; they remain distinct experimental rows but are not additional model observations. A cache record is checked against its expected identity before reuse. Temporary inference images are deleted after a run; every condition can be regenerated from frozen sources and recipes. The cache stores scores and provenance, not fabricated predictions.

`--max-new-scores` bounds actual model calls, including failed calls. Cache hits do not consume this budget. A partial run still produces a summary with expected versus observed source/condition coverage. Missing inference never becomes a zero or a guessed score. Do not interpret an incomplete condition as the intended full dataset result. Inspect failures by class and generator before using a complete case subset.

CSV and summary JSON are derived from the journals. They may be regenerated; the journals preserve the record of scoring attempts. Corrupt or incomplete journal lines raise an error for explicit repair rather than being silently discarded. A crashed attempt before its journal entry can be repeated; a completed cache entry can then supply the result without another model call.

## Evaluation and uncertainty

The existing evaluator computes condition counts, confusion matrices, AUROC with half credit for ties, AP with grouped ties, balanced accuracy, TPR, FPR, Brier score, clipped binary NLL and ten-bin positive-class ECE. Each condition reports paired score shifts and decision flips relative to its original. Ranking and balanced accuracy metrics are undefined when a label class is absent; output reasons accompany null metrics.

The benchmark replaces the evaluator's independent-source confidence interval with a **paired group cluster bootstrap**. For each baseline/condition contrast, resample `group_id` values with replacement, retaining all available real and generated source pairs in a sampled group. This preserves semantic dependence within groups and prediction dependence across processing history. This study uses 5,000 draws with seed 20261018; both values are frozen. Report the 2.5th and 97.5th percentiles of balanced accuracy differences. The same ordered groups and random seed produce corresponding draws across complete conditions.

Intervals are omitted if fewer than two paired groups or only one class is available, or if fewer than 90% of draws contain both classes. Report source counts, group counts and valid/invalid bootstrap draws. These are pointwise intervals for each contrast, not simultaneous guarantees across nine conditions. No significance claim across a selected subset of conditions is justified without a separately specified multiple comparison procedure. Source group sampling does not include uncertainty from retraining the frequency classifier, threshold selection or dataset acquisition.

Do not combine B-Free and TruFor scores. TruFor remains optional local manipulation context and is not part of this binary detector comparison. The adaptive agent's action selection, factual reporting and call budget need a separate evaluation against fixed tool workflows; the image detector benchmark does not establish an agent benefit.

## Commands and outputs

Set the project's model environment as described in `MODEL_SETUP.md`, then freeze before scoring:

```bash
python -m forensics.benchmark freeze data/benchmark/manifest.csv \
  --output output/benchmark --bootstrap-samples 5000 --seed 20261018 --threshold 0.5
```

Fit the frequency comparator using training originals and score all nine test conditions:

```bash
python -m forensics.benchmark run output/benchmark/protocol.json \
  --detector frequency --splits test
```

Run B-Free in resumable batches, or omit the cap to complete the selected split:

```bash
python -m forensics.benchmark run output/benchmark/protocol.json \
  --detector bfree --splits test --max-new-scores 100
python -m forensics.benchmark summary output/benchmark/protocol.json --detector bfree
```

At 192 test images and nine conditions, the uncached upper bound is 1,728 B-Free calls. Runtime depends on image dimensions, hardware and preprocessing. Existing integration timings are not a benchmark runtime guarantee. The frequency comparator runs separately and does not consume neural detector calls.

Inspect `protocol.json`, `frequency-model.json`, `results/<detector>/model.json`, `predictions.jsonl`, `failures.jsonl`, `predictions.csv` and `summary.json`. The completed frozen study contains all 1,728 test predictions per detector across 192 images and nine conditions, with zero failed attempts. The frequency comparator also has 576 apparent training predictions; the validation split was not scored. All paired test transformations match exactly across detectors. The B-Free worker was consolidated without changing result bytes, as recorded in `output/benchmark/consolidation.json`. Independent metric checks are recorded in `output/verification/independent-metric-check.json`. See [measured benchmark results](BENCHMARK_RESULTS.md) for actual metrics, intervals, figures and limitations; arithmetic tests and demonstration fixtures are separate from these study measurements.
