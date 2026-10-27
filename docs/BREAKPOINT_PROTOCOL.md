# Study 2 protocol: break points under single-pass resizing and JPEG

Status: **specified, not yet scored.** This file was written before any study 2 prediction existed. The frozen pilot in `output/benchmark/` is untouched; study 2 has its own protocol, journals and cache in `output/breakpoint-study/`.

## Why a second study

The pilot's primary contrast (three cumulative JPEG Q85 encodes) produced no decision changes for B-Free: balanced accuracy stayed at 100.00% with a degenerate [0, 0] interval. Resizing moved results (95.83% after three 90% resizes), and a demo image fell from 0.988 to 0.003 after three resize + JPEG rounds. Study 2 asks a narrower question the pilot cannot answer: **how much single-pass downscaling and JPEG compression does it take before B-Free's decision changes?**

These hypotheses were motivated by pilot results on the same test images. Study 2 is therefore descriptive and hypothesis-generating, not an independent confirmation.

## Design

- **Data:** the pilot manifest (`data/benchmark/manifest.csv`), test split only: 96 matched groups, 192 images. No training, tuning or threshold selection happens in study 2.
- **Detector:** B-Free with the same checkpoint; the fingerprint is frozen at protocol time. Decision rule `score > 0.5`.
- **Grid:** every cell is one pass from the normalized original: LANCZOS resize to `round(dimension × scale)`, then one encode.
  - Scale: 1.0, 0.9, 0.8, 0.7, 0.6, 0.5.
  - Encoding: lossless PNG (no JPEG), or JPEG quality 95, 85, 75, 65, 50 (4:2:0, baseline).
  - 36 cells including the original. 6,912 predictions in total.
- **Rendering and scoring:** delegated unchanged to `forensics.benchmark` (`render_condition`, `run_benchmark`), including append-only journals, provenance checks and caching.

## Endpoints

- **Primary:** change in balanced accuracy from the original to `s0.50_png` (half-size resize, no JPEG), with a 95% percentile bootstrap that resamples complete matched groups (5,000 draws, seed 20261018).
- **Secondary, descriptive:** for every cell, TPR, FPR, balanced accuracy and the fraction of sources whose decision differs from their original. Per source and per encoding row, the **break scale**: the gentlest grid scale at which the decision differs from the original, or none. Survival curves: the share of generated images still above threshold, and of real images still below it, as scale decreases.
- **Recorded, not assumed:** whether each source's decision stays changed at every smaller scale after its break point. Non-monotone counts are reported per encoding row.

## Known limits

- Scale is relative to each released original. RAISE reals were already resized to about 1 megapixel by their provider, while generated images arrive at their delivered sizes (Firefly about 4 megapixels). The same scale therefore means different absolute resolutions across classes.
- Single-pass cells do not model repeated sharing; cumulative histories remain covered by the pilot.
- Possible upstream B-Free exposure to Synthbuster applies here as in the pilot.
- Intervals describe sampling variation across matched groups, not the authenticity of any single image.

## Commands

Run on the configured Mac from the project folder:

```bash
source scripts/model-env.sh
export BFREE_DEVICE=mps
.venv/bin/python -m forensics.breakpoint freeze data/benchmark/manifest.csv --output output/breakpoint-study
.venv/bin/python -m forensics.breakpoint run output/breakpoint-study/protocol.json --max-new-scores 1000   # repeat until complete; resumes
.venv/bin/python -m forensics.breakpoint analyze output/breakpoint-study/protocol.json
```

At the pilot's measured 0.72 s per B-Free call on MPS, a full run takes roughly 85 minutes of inference. `run` resumes from its journal, so it can be split across sessions with `--max-new-scores`. `analyze` writes `analysis/bfree/breakpoint-summary.json`, `grid.csv` and `breakpoints.csv`, and refuses any protocol that is not this grid.
