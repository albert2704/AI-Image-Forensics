# Broader study proposal (historical design)

**Title:** Evaluating AI Generated Image Detection Under Repeated Compression and Resizing

**Status:** This document preserves the broader proposal from 15 October 2026; its full 1,000-image study and expanded condition grid have not been executed. The 18 October pilot uses a separate frozen [benchmark protocol](BENCHMARK_PROTOCOL.md), 320 acquired images, a group-cluster bootstrap, and the [adaptive agent design](AGENT_DESIGN.md). Use those documents and `output/benchmark/protocol.json` for the implemented pilot. Proposed crop scans, validation tuning and larger condition grids below are future work, not descriptions of the completed implementation. Unit-test scores remain isolated arithmetic fixtures, never experimental findings.

## Research question and model roles

How do repeated JPEG encoding and image resizing affect the discrimination, calibration and decision stability of an AI image detector, and can a forensics assistant communicate these changes without overstating certainty?

B-Free provides the primary binary AI image detector. Its authors motivate reducing correlations between the label and image content, format or resolution through training data design. This makes postprocessing and source matching relevant controls in this study. Use the authors' released implementation and record its exact commit, model configuration and weight checksum. [B-Free paper](https://arxiv.org/abs/2412.17671), [official inference code](https://github.com/grip-unina/B-Free/tree/main/code).

TruFor is a complementary detector of image manipulation. Its localization and reliability maps provide evidence about spatial inconsistencies, but a highlighted region does not establish AI generation. A full synthetic image may also lack a localized anomaly. Keep its image integrity score, localization map and reliability map separate from B-Free's AI score. A cropwise B-Free score map is a regional response map, not a pixel accurate forgery mask. [Official TruFor repository](https://github.com/grip-unina/TruFor).

## Prespecified hypotheses

1. Repeated postprocessing can change detector scores, balanced accuracy and calibration relative to each image's baseline. The primary test is two sided, because JPEG can remove, introduce or redistribute detectable artifacts; monotonic degradation is not assumed.
2. At the same final image dimensions, cumulative processing can produce different outcomes from one pass applied to the original. Both arms are necessary to separate processing history from final resolution.
3. Encoding repeatedly at a fixed JPEG quality and cycling through different qualities can produce different trajectories. A fixed quality sequence may stabilize, so the number of encodes is not assumed to be a linear severity scale.
4. An initially elevated score that persists under mild edits is more stable under the tested edits. Persistence alone does not establish truth or improve a calibrated probability without a separate validation study.

Primary endpoint: the paired change in balanced accuracy at a fixed validation chosen threshold from baseline to cumulative JPEG quality 85 after three encodes, without resizing. Secondary endpoints: the remaining conditions, AUROC, average precision (AP), calibration metrics, paired score changes and label flip rate. Clearly identify exploratory analyses; do not select the most favorable sequence after inspecting test results. If formal significance testing is added across multiple secondary conditions, prespecify multiplicity handling before revealing test labels.

## Dataset and split plan

The planned initial study uses 1,000 independent original images: 500 real photographs and 500 AI generated images, with 100 from each of five documented generator families where licensing and provenance permit. These are target counts, not collected counts. Select concrete datasets and versions, verify usage conditions, and store a manifest before collection. The B-Free release and its documented evaluation data are candidate starting points, not evidence that those files are already available here. Record camera/domain information for real images and generator/version information for synthetic images. Do not infer ground truth from a detector.

Use an initial development, validation and test allocation of 20%, 20% and 60%, stratified by label and generator where feasible. Keep each original and all its transformations in one split by `source_id`. Near duplicates, burst photographs, edits of the same photograph, semantic real/synthetic pairs and images from the same generation seed should receive a shared higher level group before splitting. If these dependencies remain in the test set, either retain one representative or extend resampling to that higher level group; the provided evaluator assumes independent source images. Record deduplication rules and split assignments in versioned manifests. Reserve a separate generator family for an explicitly marked unseen generator test when sufficient data are available.

Match real and synthetic content categories, starting resolution and file history as far as practical. Report their residual differences. Baseline means the delivered source image after documented decoding and orientation handling; it does not mean uncompressed camera data. Preserve original bytes and hashes. Existing JPEG history is a potential confound. Include a balanced subset with a controlled common initial encoding as a sensitivity analysis, while keeping the delivered source baseline primary. Do not silently normalize all input images to a smaller size before the baseline detector run.

Use development images for implementation checks. Use validation images only for choosing any threshold, calibration transform, regional scan policy and hyperparameters. Freeze these choices and the model before evaluating test images. The prototype defaults to `threshold=0.5`, using `score > threshold` for a positive decision, so equality is negative. The default is a declared operating point, not a claim of calibration. No threshold is fitted by `forensics.evaluation`. If a calibrator is added, fit it on validation data only, save its parameters and evaluate raw and calibrated scores separately.

## Transformation design

Record the decoder/encoder library and version, JPEG quality, chroma subsampling, resize kernel, RGB conversion, orientation handling, dimensions, round and operation order for every variant. Quality settings are encoder specific. Use the same settings for real and generated images. Preserve aspect ratio and record dimensions after rounding; stop or exclude sequences that violate the configured minimum dimensions, reporting exclusions by class and generator.

| Arm | Settings | History and control |
|---|---|---|
| Baseline | Delivered source | One baseline score per independent source |
| Fixed JPEG | Quality 95, 85, 75; rounds 1 to 5 | Cumulative: decode and reencode previous result. Independent: one encode of original at the target quality; repeated identical controls are expected |
| Varying JPEG | Example registered sequence 95, 85, 75, 85, 95 | Cumulative: encode each previous decoded result at the next quality. Independent: encode original once at that round's quality |
| Resize only | Per round factors 0.9 and 0.75; rounds 1 to 5 | Target dimensions at round r are rounded original dimensions times factor^r in both arms |
| Resize then JPEG | Factors 0.9 and 0.75; quality 85; rounds 1 to 5 | Resize to the target dimensions then encode; cumulative and independent histories |
| JPEG then resize | Same final dimensions, quality and round counts | Separate order ablation; save the final resized output losslessly to avoid an unplanned extra JPEG step |

Cumulative resizing starts from the previous decoded result; independent resizing starts from the original and reaches the same target dimensions in one pass. Comparing repeated resizing with a single resize to only the first round's dimensions would confound history with final resolution. For combined arms, repeat the complete named operation sequence in each cumulative round. Independent combined arms apply that same sequence once to the original using the current target dimensions. Separate experiment IDs encode all parameters and order.

The current prototype supports up to five rounds, both history modes and both operation orders. Its quality setting is fixed within a run; varying quality sequences remain a planned extension. A supported condition is not a completed experiment until inference has run on the dataset. For quality measurements after resizing, compare the variant with the original directly resized to the same dimensions. MSE and PSNR summarize that defined pixel difference; they are neither detector accuracy nor proof of image authenticity.

## Assistant experiment

The assistant first inspects the image dimensions and records a baseline detector result. An optional regional scan uses a fixed crop size and stride, with crop coordinates and boundary treatment recorded. Its trigger policy is fixed on validation data. Requesting a regional scan does not change the baseline image label or permit tuning on the test set. For a regional scan figure, report crop size, overlap, how crop scores are combined, any model input resizing and interpolation used for the display. Overlap and interpolation make neighboring heatmap pixels dependent.

Apply a small, prespecified stability panel to every image selected by that policy, for example quality 95 and one 0.9 resize round. Display measured scores and deltas, the tested transformations and whether the decision crossed the fixed threshold. Report the percentage of images sent to regional scans, detector calls and runtime, and compare the policy with the same baseline detector used without extra scans. Without such a controlled comparison, the assistant is an analysis workflow, not evidence of higher detection accuracy.

Display uncertainty as limits of the evidence. Scores can be affected by generator shift, resizing, compression, crop context and unknown image provenance. A missing model or failed inference produces no score. Do not substitute a heuristic, demonstration number or artifact heatmap for a model output. Stable low scores do not prove that an image is authentic; stable high scores do not prove that it is generated.

## Metrics and paired uncertainty

The input CSV contains `source_id,label,generator,condition,score`. `label=1` means AI generated, and the score must be a finite probability for that label in [0, 1]. Use `generator=real` for real images and `condition=baseline` for the reference. Each source/condition pair is unique. The evaluator rejects changing labels or generator metadata across variants. Run one detector and one declared calibration setting per CSV; combining detector outputs as if they were new independent images is invalid.

For each condition, report total, real and generated source counts, generator counts, the confusion matrix, AUROC, AP, balanced accuracy, TPR, FPR, accuracy, Brier score, binary negative log likelihood (NLL) and expected calibration error (ECE). AUROC gives half credit to tied positive/negative scores. AP groups all equal scores before updating precision and recall. AUROC, AP and balanced accuracy are intentionally null when either class is absent. TPR or FPR is null when its denominator class is absent, with a reason in the output. AP depends on class prevalence, so do not compare it across datasets with different class ratios without qualification.

NLL uses natural logarithms and clips probabilities to [1e-15, 1-1e-15] only for numerical safety. Brier uses the supplied probabilities without clipping. ECE compares mean positive class probability with the positive fraction in ten equal width bins. Bins include their lower boundary and exclude their upper boundary, except the final bin includes 1. Empty bins have count zero and null means. The JSON includes every bin so calibration claims can be inspected; ECE alone can hide problems in small samples. This is positive class calibration ECE, not confidence of the predicted class.

Pair each nonbaseline condition with baseline by `source_id`. Compute mean, median and mean absolute score change, class specific mean score changes, label flip rate and directional flip counts on that intersection. Calculate balanced accuracy change using the same paired subset in both conditions, rather than subtracting unrelated condition totals. Report counts of unmatched sources and the number of pairs in each class. Investigate failures and missing variants; a complete case result can be biased when failures depend on label or severity.

The 95% balanced accuracy change interval uses 1,000 class stratified paired bootstrap resamples, seed 2026. Sample original source IDs with replacement within each class and keep their baseline/condition predictions together. Resampling variants independently would underestimate dependence. The interval is the 2.5th to 97.5th percentile of paired differences and conditions on observed class counts and paired availability. Return null with a reason when pairing is absent, either class is missing, either paired class has fewer than two independent sources, or bootstrap is disabled. A narrow interval with very few sources is not evidence of broad generalization. For the final study, increase to at least 5,000 resamples and prespecify the count before running. This interval does not include uncertainty from model training or threshold selection.

For generator specific reporting, run the evaluator on each generator's positives plus a prespecified shared or matched real reference subset, and disclose that reference reuse makes subgroup estimates dependent. Also report pooled metrics. Do not average a set of positive only generator AUROCs or relabel real images as generator specific fakes. Additional localization metrics require pixel ground truth; no segmentation accuracy claim is made from an AI image label alone.

## Reproduction and results status

From the project root, evaluate measured predictions with:

```bash
python -m forensics.evaluation predictions.csv \
  --output outputs/evaluation.json \
  --threshold 0.5 --bootstrap-samples 5000 --seed 2026
python -m unittest discover -s tests -p test_evaluation.py -v
```

Archive source and split manifests, variant parameters, model and software versions, hardware, weight checksums, threshold/calibration records, detector failures, per image outputs and JSON evaluations. Record elapsed inference time separately from model initialization and image transformations. Present a condition by condition metric table and trajectories by round, with source counts and paired confidence intervals. Show representative heatmaps selected using a declared rule, including false positives and false negatives when labeled data exist.

**This broader proposal remains unexecuted.** The separately frozen 320-image pilot is documented in [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md), with its measured outputs in [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md). Its results do not establish that B-Free or TruFor is universally robust to repeated compression or resizing. Interpret every finding within the executed dataset's coverage.
