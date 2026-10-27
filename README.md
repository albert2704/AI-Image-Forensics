# AI Image Forensics Assistant

A local research prototype for **Evaluating AI-Generated Image Detection Under Repeated Compression and Resizing**.

Inspect an image, compare B-Free responses under compression and resizing, request a TruFor regional scan, or let a bounded local language model choose investigation steps. Export measured evidence and uncertainty. The project includes a frozen 320-image research pilot and a train-only FFT/DCT classifier baseline.

## Start

The models and isolated Python environment are already installed on this Mac. Double-click `start.command`, or run from this project directory:

```bash
bash scripts/start-with-models.sh
```

Open **http://127.0.0.1:8765**. The interactive B-Free and TruFor adapters default to CPU; the local planner automatically uses Apple MPS when available. The completed benchmark uses verified B-Free MPS inference. The first analysis loads models; large regional scans can take several minutes.

For a new machine, the base transformation workflow can be installed with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m forensics.server
```

The server binds only to the local machine. Uploaded images and generated outputs stay in `output/runs/`; remove a run directory to delete its saved source and derivatives.

For real neural inference, follow [MODEL_SETUP.md](docs/MODEL_SETUP.md). Without a model, the image transformation and measurement workflow still works, but every detector score remains missing. Missing inference never becomes a heuristic score or a fabricated heatmap.

## Workflow

Choose **Fixed experiment** for an explicit, repeatable transformation trajectory, or **Adaptive investigation** for observation-driven tool selection. Adaptive mode uses local Qwen2.5-1.5B-Instruct, starts with one required B-Free measurement, then chooses allowed tests or finishes. Its default budget is four model-tool calls including the original. The report cites evidence IDs and computes its claims from actual measurements. Cancellation stops between calls. See [AGENT_DESIGN.md](docs/AGENT_DESIGN.md).

1. Upload a single JPEG, PNG or WebP image. The backend also reads single-frame BMP/TIFF. The limit is 20 MiB and 20 megapixels; both dimensions must initially be at least 16 pixels.
2. Choose JPEG, resizing, or both; quality 50-100, scale 0.5-1.0 and 1-5 rounds. For both operations choose their order.
3. Choose cumulative processing or a matched-size single-pass control. Every round records its dimensions, bytes, exact operations, parent hash, MSE, PSNR and available model score.
4. Compare original and derivative images and the score trajectory. The assistant recommends further investigation when evidence is elevated, close to the threshold, or changes across it.
5. Request the optional TruFor scan. Inspect the manipulation anomaly, reliability and overlay separately from B-Free's AI-generation score. Export JSON and CSV.

## Scientific meaning

- **B-Free:** AI-generation evidence. We retain the raw logit and display its sigmoid on a 0-1 scale. The default positive decision is strictly `score > 0.5`, equivalent to the official logit rule `> 0`. This is not a guaranteed probability that an image is fake.
- **TruFor:** local manipulation evidence, reliability map and image forgery score. A highlighted region is not proof of AI generation. These outputs are never combined into one confidence number.
- **Cumulative:** apply the next operations to the previous round's decoded image. At round `r`, resizing targets `round(original_dimension * scale**r)`.
- **Single-pass control:** start from the original for every condition, resize directly to that same target, and encode JPEG once. JPEG-only controls can be identical; they are deliberate controls, not extra independent evidence.
- **Distortion:** compare each derivative to the original RGB image resized directly to that derivative's dimensions using LANCZOS. PSNR is infinite when MSE is zero (JSON uses `null` plus an explicit convention). Distortion is not AI evidence.
- **Normalization:** preserve source bytes; apply EXIF orientation, convert to RGB, composite transparency on white, and record the changes. The baseline preview is lossless PNG. Stored artifact sizes are not directly comparable as compression ratios across different formats.

## Reproduce experiments

Analyze one image:

```bash
python -m forensics.cli --image examples/processing-fixture.png \
  --quality 90 --scale 0.9 --rounds 3 --mode cumulative
```

The included fixture is an artificial geometric test image for checking the processing code. It is not a labeled real/AI benchmark.

Create a manifest CSV with `source_id,path,label,generator`. Paths are relative to the manifest; label 1 means AI-generated and 0 means real. Acquire and document the actual images separately. Use a separate output directory for each experimental arm:

```bash
python -m forensics.cli --manifest data/test.csv --operation jpeg \
  --quality 85 --rounds 3 --output output/jpeg-q85
python -m forensics.evaluation output/jpeg-q85/predictions.csv \
  --output output/jpeg-q85/evaluation.json --bootstrap-samples 5000
```

Batch evaluation requires the real detector and rejects missing scores. The evaluator reports AUROC, AP, balanced accuracy, TPR/FPR, Brier, NLL, ECE, paired score shifts, label flips and paired bootstrap intervals. Keep images and all derivatives in the same data split. A source image is the independent unit; transformed variants are correlated.

The legacy CSV evaluator uses source-level resampling. For matched real/generated groups, use the frozen benchmark runner below, which resamples complete groups. Variable-quality sequences and learned calibration remain future work.

## Frozen benchmark and policy evaluation

The documented pilot contains 320 images from four Synthbuster generator families and matched RAISE photographs, grouped into 64 training, 64 validation and 192 test images. Source-dependent resolution/preprocessing is an important confound. Validation is reserved and unused; the classical baseline fits training originals only. See [DATASET.md](docs/DATASET.md) and [BENCHMARK_PROTOCOL.md](docs/BENCHMARK_PROTOCOL.md).

```bash
source scripts/model-env.sh
export BFREE_DEVICE=mps  # The delivered protocol freezes this device.
.venv/bin/python -m forensics.benchmark run output/benchmark/protocol.json --detector bfree --splits test
.venv/bin/python -m forensics.benchmark run output/benchmark/protocol.json --detector frequency --splits train test
.venv/bin/python -m forensics.agent_evaluation run output/agent-evaluation/protocol.json
```

These commands resume existing journals; they do not silently refit settings or repeat completed predictions. To create a new study, run `scripts/acquire_benchmark.py`, then `python -m forensics.benchmark freeze data/benchmark/manifest.csv --output output/new-study --bootstrap-samples 5000 --seed 20261018` in the configured environment. Keep the delivered frozen protocol intact. The runner rejects changed source files, model identity, preprocessing or frozen implementation.

Measured outputs live in `output/benchmark/results/{bfree,frequency}/`, with figures in `output/benchmark/figures/`. The 24-source policy replay and its exact input snapshot live in `output/agent-evaluation/`. Replay measures policy selection and tool-call cost; it is not an end-to-end latency benchmark or an authenticity-accuracy comparison.

## Research deliverables

- [Research write-up](docs/RESEARCH_WRITEUP.md) and `output/pdf/AI_Image_Forensics_Research_Report.pdf`.
- [Measured benchmark results](docs/BENCHMARK_RESULTS.md), [agent-policy results](docs/AGENT_RESULTS.md), [agent design](docs/AGENT_DESIGN.md), and [adaptive UI verification](docs/AGENT_UI_QA.md).
- [Experiment protocol](docs/EXPERIMENT_PROTOCOL.md): hypotheses, datasets, controls, splits, metrics and limits.
- [Model setup](docs/MODEL_SETUP.md): official sources, exact revisions, checkpoint setup and inference contracts.
- [UI research](docs/UI_RESEARCH.md): inspected Mobbin references and design decisions.
- `output/verification/processing-check.json`: measured cumulative and single-pass transformations of the geometric fixture. No AI scores are invented.
- `output/model-verification/trajectory.json`: actual B-Free scores for an official demo across three cumulative resize/JPEG rounds. The score changed from 0.988232 to 0.002742; this is one illustrative case, not benchmark performance.
- `output/model-verification/bfree-reference-check.json`: actual logits on four upstream demo images matched the supplied reference within 0.000017.
- `output/model-verification/trufor-small-reference-check.json`: actual TruFor localization, reliability and overlay on an official 256 x 256 demo image.

Run software checks:

```bash
python -m unittest discover -s tests -v
```

Rebuild the typeset report after measured results and figures are complete:

```bash
python -m pip install -r requirements-report.txt
python scripts/build_report.py
```

The report generator reads the frozen summaries, checks coverage and protocol identity, and writes both the PDF and editable Markdown. It refuses to label partial results as a completed study.

## Limits and attribution

This is a research prototype with a fixed workflow and an optional local language-model policy. The adaptive dispatcher and factual report builder enforce deterministic constraints; the model selects the next action from the observations. It has no account system or public deployment. Run only on localhost. A stable score is repeatability under the tested operations, not verification of origin. Small images, unknown generators, prior editing and compression can all affect evidence. Confidence intervals quantify sampling uncertainty within the pilot, not the probability an individual image is authentic. The pilot does not establish performance on unseen generator families or erase possible upstream B-Free exposure to Synthbuster.

Official models and their weights retain their authors' terms, including informational/nonprofit restrictions. See the upstream licenses before reuse:

- Guillaro et al., [B-Free: A Bias-Free Training Paradigm for More General AI-generated Image Detection](https://arxiv.org/abs/2412.17671), [official code](https://github.com/grip-unina/B-Free).
- Guillaro et al., [TruFor: Leveraging All-Round Clues for Trustworthy Image Forgery Detection and Localization](https://github.com/grip-unina/TruFor), CVPR 2023.
- Qwen Team, [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct), Apache-2.0; install with `.venv/bin/python scripts/install-planner.py` in the model environment.
- [Synthbuster](https://zenodo.org/records/10066460), CC BY-NC-SA 4.0; [RAISE](https://loki.disi.unitn.it/RAISE/), scientific/research and noncommercial terms retained with the dataset.
