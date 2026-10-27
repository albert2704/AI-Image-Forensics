# Dataset: grouped Synthbuster / RAISE pilot

This is a **320-image pilot sampled from established public research datasets**. It is not the full Synthbuster benchmark and does not establish broad real-world detector accuracy. The selection, family allocation and splits are fixed before model inference.

Acquisition is implemented by `scripts/acquire_benchmark.py`. The user-readable manifest is `data/benchmark/manifest.csv`; it is published only after every prespecified image has downloaded and passed integrity checks. The immutable selection record is `data/benchmark/metadata/selection-plan.json`. Actual completion, transferred bytes, failures and manifest hash are recorded in `data/benchmark/metadata/acquisition-status.json`.

Acquisition and the independent data audit completed on **18 October 2026**, before any pilot detector scores were computed. All 320 prespecified images passed size, ZIP CRC32, SHA-256 and decoding checks; no images were substituted. One timed-out range request succeeded on resume. The first attempt is retained as `metadata/acquisition-attempt-1.json`. Across both attempts, 569,316,703 response bytes were received, including image members, metadata and ZIP directory data.

The final manifest SHA-256 is `fdaae67c8593aa126e69fd9da0b9e11ff5542fd89ac42ca4fe36c326ab038ca5`. The audit in `metadata/integrity-audit.json` verifies 160 matched groups, the prespecified split counts, 160 source-prompt matches, no normalized-pixel duplicates and no groups crossing splits. A cross-group perceptual hash screen found no candidates within four of 63 bits; this limited heuristic does not establish absence of near-duplicate, burst or event dependence. The audit is reproducible with `.venv/bin/python scripts/audit_benchmark_data.py data/benchmark/manifest.csv` and executes no detector.

## Primary sources and provenance

Synthetic images come from Quentin Bammey's **Synthbuster v1**, DOI `10.5281/zenodo.10066460`. The original release contains 1,000 images from each of nine generators. This pilot prespecifies four: DALL·E 3 (`dalle3`), Adobe Firefly (`firefly`), Midjourney v5 (`midjourney-v5`), and Stable Diffusion XL (`stable-diffusion-xl`). The source release records these family labels; we do not infer them from image appearance or detector responses. Precise service versions beyond the source's documentation are unknown. [Official dataset record](https://zenodo.org/records/10066460)

Real photographs come from the **official GRIP/B-Free release of RAISE-1k**, available in the authors' extended Synthbuster directory. It is derived from the RAISE research dataset. B-Free's authors state that these real images have been resized to approximately a 1024 × 1024 pixel area. We preserve the released PNGs and record that earlier resampling. This baseline therefore means the delivered research image, not untouched camera RAW. [Official directory](https://www.grip.unina.it/download/prog/B-Free/extended_synthbuster/), [B-Free release description](https://github.com/grip-unina/B-Free#dataset-of-new-generators), [RAISE source and terms](https://loki.disi.unitn.it/RAISE/download.html)

Synthbuster generates images from descriptions associated with RAISE-1k photographs. The shared file stems were checked against all five selected folders: the real release and each of the four synthetic families. There are exactly **1,000 common stems**. Every selected real/fake pair uses the same verified stem. These are semantic/prompt-related pairs, not pixel-aligned edited versions of the same photograph. The full released prompt CSV is retained in `metadata/Synthbuster-prompts.csv`.

## Sampling and split rule

No sample selection depends on a detector score, image quality score, visual attractiveness, or expected success. The rule is:

1. Intersect the source stems from the real folder and all four synthetic folders.
2. Rank all 1,000 stems by SHA-256 of the UTF-8 string `forensics-pilot-v1|20261018|<stem>`.
3. Select the first 160 stems without replacement.
4. Assign one synthetic family per stem by ranked position modulo four, in the fixed order `dalle3`, `firefly`, `midjourney-v5`, `stable-diffusion-xl`.
5. Within each family's 40 source groups, rank by SHA-256 of `forensics-pilot-v1|20261018|split|<stem>`. Assign the first eight groups to train, the next eight to validation, and the remaining 24 to test.
6. Include exactly one real photograph and its assigned family's synthetic image for every selected group. Include each real photograph once.

| Split | Matched source groups | Real photographs | Synthetic images | Total images |
|---|---:|---:|---:|---:|
| Train | 32 | 32 | 32 | 64 |
| Validation | 32 | 32 | 32 | 64 |
| Test | 96 | 96 | 96 | 192 |
| Total | 160 | 160 | 160 | 320 |

Each synthetic family contributes 8 train, 8 validation and 24 test images, plus the same number of distinct matched real references. The resampling unit is the **matched source group**, not a transformed image or an individual real/fake member; between-group independence remains an assumption. Groups never cross splits. The benchmark runner must preserve this group structure for bootstrap intervals. Fitting, threshold selection, calibration and policy-development tuning must use train/validation data; test outcomes must not drive revisions. During evaluation, the frozen adaptive policy may choose its next action from that test image's already-observed measurements, without receiving its truth label.

## Manifest contract and acquisition integrity

The required columns are `source_id,path,label,generator,group_id,split,sha256,source_url`. `label=0` means real and `label=1` means AI-generated. Real rows have `generator=real`; `paired_generator` records their matched synthetic family's stratum. Paths are relative to the manifest. `group_id=raise1k:<stem>` is shared by the two members; `source_id` also includes dataset and family so each image has a unique identifier.

Additional columns preserve the exact ZIP member, license, dimensions, bytes, image format/mode, original dataset page, provider preprocessing and original ZIP CRC32. `source_url` points to the official archive; `archive_member` identifies the precise file inside it. Archive byte sizes, ETags where supplied, last-modified headers, member offsets, sizes and CRCs are frozen in metadata before image transfer.

Only ZIP directory records and the selected member byte ranges are downloaded. The original Synthbuster archive is about 12.4 GB and the real archive about 1.65 GB; neither is downloaded in full. Selected compressed image data total **566,839,267 bytes**, roughly 541 MiB. The script imposes a 2 GB transfer ceiling including retries and refuses HTTP responses that ignore range requests. Successful members must match the frozen archive's size and CRC, decode as images, and receive SHA-256 hashes. Original PNG bytes are saved unchanged. The full-archive MD5 cannot be independently verified from a partial download; member CRCs and local hashes are not presented as that verification.

Failed images are recorded and retried on resume. They are never silently replaced with other candidates. An incomplete acquisition does not publish a complete manifest. Model scoring is not part of the acquisition script. The separate benchmark freeze validates image hashes, normalized pixel duplicates and split/group integrity before inference.

## Usage terms and citation

The original `synthbuster/LICENCE.txt` explicitly identifies **CC BY-NC-SA 4.0**. A verbatim copy is stored as `metadata/Synthbuster-LICENCE.txt`. The pilot retains attribution and the original terms. [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)

RAISE permits scientific, noncommercial uses such as academic research, teaching and personal experiments, requires citation, and requires copyright, license and source-link retention in copies or derivatives. Commercial use or distribution requires written permission. The official archive's `RAISE_License.pdf` and explanatory README are preserved in metadata. Dataset images are local research inputs; this project does not claim a separate unrestricted license over them.

Cite:

- Quentin Bammey. *Synthbuster: Towards Detection of Diffusion Model Generated Images*. IEEE Open Journal of Signal Processing, 2023. Dataset DOI: `10.5281/zenodo.10066460`.
- Duc-Tien Dang-Nguyen, Cecilia Pasquini, Valentina Conotter, and Giulia Boato. *RAISE: A Raw Images Dataset for Digital Image Forensics*. ACM MMSys, 2015, pp. 219–224.
- The B-Free authors and repository for the released resized RAISE-1k files, alongside the detector citation already recorded in `MODEL_SETUP.md`.

## What this pilot can and cannot establish

The central question is the paired change caused by the prespecified postprocessing of each source image. The class-balanced and grouped design avoids counting the same real photograph repeatedly or splitting matched semantic content across train and test.

Provider history still differs: the real release has already been resampled; Synthbuster reports no post-generation JPEG compression or resampling. Starting dimensions, camera sources and generation services also differ. Report these distributions and treat them as potential confounds in absolute discrimination or calibration claims. A common-size sensitivity analysis can inform this issue, but it cannot reconstruct missing provenance or turn the delivered files into camera originals.

The acquired files total 567,411,882 bytes. All are PNG: 280 RGB and 40 RGBA. Real photographs have approximately 1.05 million pixels, DALL·E 3 has 1.05–1.84 million, Firefly has 4.13–4.19 million, Midjourney v5 has 1.20–1.22 million, and SDXL dimensions vary around one million. Exact per-family dimension counts are in the audit. The analysis applies its documented RGB/white-background normalization; container mode and resolution are therefore recorded rather than silently treated as equivalent acquisition histories.

The selection covers four named generator families from one established collection and a small real-photo source. There is no held-out generator family in this pilot: each selected family appears in all splits. It is not a test of generalization to every new generator or to social media images. Exact normalized duplicates are rejected by the benchmark freeze; unannotated near-duplicates, bursts and event-level dependencies can remain because neither archive provides those groups. Claims and uncertainty intervals should acknowledge this residual dependence.

Synthbuster is an established evaluation collection used in the B-Free research context. A test split held out from this project's fitting and policy choices is not evidence that these images were unseen during all upstream detector development or model selection. The released checkpoint is fixed; no independence from its authors' development process is claimed.

Reproduce acquisition from the project root with:

```bash
.venv/bin/python scripts/acquire_benchmark.py --output data/benchmark
```

The same command resumes failed transfers against the existing frozen selection. To inspect the protocol without downloading images, add `--plan-only`. Do not regenerate a selection in place after inspecting detector results.
