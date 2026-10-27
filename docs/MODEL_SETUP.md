# Real detector and local planner setup

The application works without research checkpoints, but then reports **AI scoring unavailable**. Image measurements and image transformations are still real. No generated score or decorative heatmap substitutes for a detector result.

The adaptive workflow also uses the official local Qwen2.5-1.5B-Instruct model. Install it with `.venv/bin/python scripts/install-planner.py` after installing the model environment below. The script pins revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`; the adapter verifies checkpoint, tokenizer and configuration hashes before loading. No API credentials are needed. Default `FORENSICS_PLANNER_DEVICE=auto` selects Apple MPS where available; `cpu` forces CPU. The verified planner runs in float32 because FP16 produced invalid MPS logits. Details, budget semantics and evaluation limits are in [AGENT_DESIGN.md](AGENT_DESIGN.md).

On 18 October 2026, B-Free MPS inference was checked against the four earlier CPU reference runs: maximum absolute logit difference was 0.000035 and all threshold decisions agreed. The completed detector pilot freezes `BFREE_DEVICE=mps`. The interactive launch script retains CPU as its conservative B-Free default. See `output/model-verification/bfree-mps-validation.json`.

The official B-Free checkpoint is installed locally and has been run on all four bundled reference images on this Apple Silicon Mac. Its logits match the published reference values within 0.000017. This verifies integration, not independent detection accuracy. The measured evidence and provenance are in `output/model-verification/bfree-reference-check.json`. TruFor is also installed and has produced validated native-resolution numerical maps, reliability maps and overlays on official examples; details are below.

## Reviewed sources and meaning of outputs

Upstream `main` revisions queried on 15 October 2026:

| Model | Source revision | Intended evidence |
|---|---|---|
| B-Free | `c6a9f898782fb466b29af01f21960b67415afb0e` | Whole-image evidence of AI generation |
| TruFor | `ae54475df6f41a491d7615100feb19263dec13f7` | Local manipulation anomalies and localization reliability |

The adapter records the installed Git revision and SHA-256 of the checkpoint for each successful result. A ZIP download has no Git revision; the value is then null. Prefer the pinned checkouts below and keep local modifications out of the external repositories during experiments.

B-Free returns a logit, with larger values supporting AI generation and the upstream classification threshold at `logit > 0`. We preserve that logit and expose its sigmoid as a bounded score. The bounded score is **not an independently calibrated probability**. The code can return either one logit or the difference of fake and real logits. [Official inference implementation](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/main_bfree.py)

B-Free converts to RGB and applies normalization from its checkpoint configuration. Its wrapper operates on five 504 × 504 views of patch embeddings, averages their predictions, and repeats embeddings when the image is too small. The adapter retains this behavior and does not silently resize the input. Small crops may therefore behave differently from full images. Any regional B-Free scan is a crop sensitivity map, not native pixel localization. [Normalization](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/utils/normalization.py), [five-view wrapper](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/networks/wrapper5crops.py)

TruFor supplies a softmax localization map, sigmoid confidence map, and sigmoid image-level manipulation score. Higher confidence means the localization prediction is expected to be more reliable; it is not a second AI-generation score. Its loader uses RGB values divided by **256.0**, with ImageNet normalization subsequently applied inside the model. Use its own loader rather than substituting `/255` preprocessing. [Inference](https://github.com/grip-unina/TruFor/blob/ae54475df6f41a491d7615100feb19263dec13f7/TruFor_train_test/test.py), [loader](https://github.com/grip-unina/TruFor/blob/ae54475df6f41a491d7615100feb19263dec13f7/TruFor_train_test/dataset/dataset_test.py), [model](https://github.com/grip-unina/TruFor/blob/ae54475df6f41a491d7615100feb19263dec13f7/TruFor_train_test/lib/models/cmx/builder_np_conf.py)

TruFor is a local forgery detector. Its map must be labelled **manipulation anomaly**, not “AI-generated pixels.” A completely generated image may have no localized inconsistency. Agreement between B-Free and TruFor is useful context, not independent proof of authenticity or generation. [Official project description](https://github.com/grip-unina/TruFor)

## Start the installed models

From the project directory, run `bash scripts/start-with-models.sh`, then open http://127.0.0.1:8765. This selects the local `.venv`, B-Free and TruFor paths, CPU inference, and four CPU threads. For CLI work, first run `source scripts/model-env.sh` and use `.venv/bin/python`. All model sources and weights remain inside `external/`; no shared runtime was modified.

The verified environment uses Python 3.12, PyTorch 2.5.1, torchvision 0.20.1 and timm 1.0.12. Its complete installed package list is saved in `output/model-verification/requirements-installed.txt`. These differ from the upstream historical environment; the reference-image comparison is therefore an essential compatibility check.

## B-Free installation

The commands below reproduce the native CPU setup used here. They require Python 3.12, Git, curl, and unzip. PyTorch 2.5.1 and torchvision 0.20.1 provide Python 3.12 wheels; timm and transformers retain the upstream versions. The environment pins NumPy 1.26.4. Use a separate project environment rather than changing a system Python. The upstream requirements list uses `pytorch` and `yaml`; their pip package names are `torch` and `PyYAML`. [Upstream Dockerfile](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/Dockerfile), [requirements](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/requirements.txt)

Run from the project directory:

```bash
mkdir -p external
git clone https://github.com/grip-unina/B-Free.git external/B-Free
git -C external/B-Free checkout c6a9f898782fb466b29af01f21960b67415afb0e
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install torch==2.5.1 torchvision==0.20.1 timm==1.0.12 transformers==4.43.4 numpy==1.26.4 Pillow PyYAML pandas tqdm scikit-learn
curl -fL 'https://www.grip.unina.it/download/prog/B-Free/weights/BFREE_dino2reg4.zip' -o external/BFREE_dino2reg4.zip
.venv/bin/python -c 'import hashlib,pathlib; p=pathlib.Path("external/BFREE_dino2reg4.zip"); assert hashlib.md5(p.read_bytes()).hexdigest()=="f3f53fa647848b16cf81c913f148a198", "Checkpoint ZIP checksum mismatch"'
mkdir -p external/B-Free/code/weights
unzip external/BFREE_dino2reg4.zip -d external/B-Free/code/weights
export BFREE_REPO="$PWD/external/B-Free"
export BFREE_WEIGHTS="$PWD/external/B-Free/code/weights/BFREE_dino2reg4"
export BFREE_DEVICE=cpu
```

Expected files: `BFREE_WEIGHTS/config.yaml` and `BFREE_WEIGHTS/model_epoch_best.pth`. The checkpoint archive and its MD5 are published by the authors. MD5 here checks download consistency; record the adapter's SHA-256 for experiment provenance. [Checkpoint instructions](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/README.md)

Run the application with `.venv/bin/python` so the persistent adapter can import PyTorch. Install the application's own requirements into that same environment if needed.

Upstream reference check (from `external/B-Free/code`, with the environment active):

```bash
python main_bfree.py -i demo_images/metainfo.csv -o smoke-results.csv -d cpu
```

Compare with `demo_images/results.csv`; the published logits for `img0000.png` through `img0003.png` are approximately `-5.9375`, `-4.4419`, `4.4305`, `3.8500`. They are upstream reference values, **not results measured by this project**. Allow small numerical differences and investigate large differences before evaluating your data. [Reference outputs](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/demo_images/results.csv)

For a single image, the correct command is `python main_bfree_single.py -i /absolute/image.png -d cpu`. The README's single-image example incorrectly supplies a CSV and `-o`; the actual single-image parser accepts neither that CSV format nor an output flag. [Single-image parser](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/main_bfree_single.py)

## TruFor installation and optional regional investigation

The installed TruFor adapter uses the same isolated `.venv` as B-Free. Its needed timm layer imports are retained in timm 1.0.12. The complete official conda file targets Linux/CUDA and is not a native Apple Silicon environment. This is an adapted Python 3.12/PyTorch 2.5.1 inference environment, **not a reproduction of the original software stack**. For the historical upstream environment on a compatible Linux host, use the repository's conda environment or Docker instructions instead. [Conda environment](https://github.com/grip-unina/TruFor/blob/ae54475df6f41a491d7615100feb19263dec13f7/TruFor_train_test/trufor_conda.yaml), [Docker instructions](https://github.com/grip-unina/TruFor/tree/ae54475df6f41a491d7615100feb19263dec13f7/test_docker)

From the project directory:

```bash
git clone https://github.com/grip-unina/TruFor.git external/TruFor
git -C external/TruFor checkout ae54475df6f41a491d7615100feb19263dec13f7
.venv/bin/python -m pip install numpy==1.26.4 matplotlib==3.9.2 contourpy==1.3.2 yacs==0.1.8
curl -fL 'https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip' -o external/TruFor_weights.zip
.venv/bin/python -c 'import hashlib,pathlib; p=pathlib.Path("external/TruFor_weights.zip"); assert hashlib.md5(p.read_bytes()).hexdigest()=="7bee48f3476c75616c3c5721ab256ff8", "Checkpoint ZIP checksum mismatch"'
unzip external/TruFor_weights.zip -d external/TruFor/TruFor_train_test/pretrained_models
mv external/TruFor/TruFor_train_test/pretrained_models/weights/trufor.pth.tar external/TruFor/TruFor_train_test/pretrained_models/trufor.pth.tar
export TRUFOR_REPO="$PWD/external/TruFor"
export TRUFOR_PYTHON="$PWD/.venv/bin/python"
export TRUFOR_DEVICE=cpu
```

The required final path is `external/TruFor/TruFor_train_test/pretrained_models/trufor.pth.tar`. The official archive contains a `weights/` subdirectory; the move command above places the checkpoint where this adapter expects it. [Official inference/checkpoint instructions](https://github.com/grip-unina/TruFor/blob/ae54475df6f41a491d7615100feb19263dec13f7/TruFor_train_test/README.md)

Run the wrapper using a Python environment with the application's NumPy and Pillow dependencies:

```bash
python scripts/run_trufor.py /absolute/image.png --output output/regional
```

It creates a unique run directory, invokes the official `test.py`, rejects missing or invalid outputs, and returns JSON with absolute `heatmap_path`, `reliability_path`, and `npz_path`. The heatmap always uses the fixed 0–1 scale; the grayscale reliability image maps 0 to black and 1 to white. The NPZ preserves the numerical maps for analysis. Upstream skips existing result files, so a unique directory is required for every run. A process exit code of zero alone does not prove success: upstream catches some inference errors. Our wrapper also requires a valid output archive.

To run upstream directly, change into `external/TruFor/TruFor_train_test`:

```bash
python test.py -g -1 -in /absolute/image.png -out /absolute/output/result.npz -exp trufor_ph3 TEST.MODEL_FILE pretrained_models/trufor.pth.tar
```

## Measured TruFor integration outputs

Both checks used the same local Python 3.12/PyTorch 2.5.1/timm 1.0.12 environment as B-Free. The official checkpoint SHA-256 is `ac1d90e329a72e0d66e8665e123a19e94bfae3209c3ef8a4f9ca3b91578c7844`.

| Upstream input | Native dimensions | Manipulation score | Wall time |
|---|---|---|---|
| `tampered1.png` | 2048 × 1536 | 0.9976143 | 181.4 seconds |
| `tampered2.png` | 256 × 256 | 0.9983463 | 14.7 seconds |
| B-Free `img0002.png` | 1024 × 1024 | 0.0322388 | 28.0 seconds |

These are measured integration examples, not independent ground-truth validation or a speed benchmark. The small-image run overlapped the end of the large-image run. Full JSON, source URLs and input hashes are in `output/model-verification/trufor-reference-check.json` and `output/model-verification/trufor-small-reference-check.json`. Each points to the original numerical NPZ, anomaly heatmap, reliability image and overlay. No input resizing was applied by the wrapper. A visual inspection confirmed that the rendered small-image map and overlay correspond to the saved map. [Official sample images](https://github.com/grip-unina/TruFor/tree/ae54475df6f41a491d7615100feb19263dec13f7/test_docker/images)

The B-Free example result is saved in `output/model-verification/trufor-bfree-example.json`, with its own input SHA-256 and source URL. Its B-Free baseline score is 0.9882320 while its TruFor manipulation score is 0.0322388. This is not a contradiction: the detectors address whole-image AI generation and localized manipulation respectively. It does not establish authenticity or general performance.

## Devices, reporting, and license

- CPU is exposed by both projects. B-Free accepts a torch device string; the adapter accepts `cpu`, `cuda:N`, or experimental `mps`. Its Apple GPU behavior has not been tested here.
- TruFor's official CLI exposes CPU (`-g -1`) and CUDA indices; it does not expose MPS. The adapter rejects MPS explicitly. B-Free CPU inference has been measured here: 14.1 seconds for the initial call including model load, then approximately 3.3–5.7 seconds for the remaining reference images using four CPU threads. These are one-run integration timings, not a performance benchmark.
- Keep original pixels as the baseline and record any imposed resolution limit. Native TruFor processes arbitrary sizes at batch size one, so large images can require substantial memory. Compression, resampling, cropping, and low resolution can erase or introduce detector cues.
- Do not fuse B-Free and TruFor scores into a single probability. Report the two tasks separately. Repeated transformations of the same source are correlated observations, not independent evidence.

Both repositories restrict the covered software to informational and nonprofit use, require retention of notices, and require credit when results are made public. This academic project should retain the authors' licenses alongside downloaded sources. Commercial use needs separate permission. [B-Free license](https://github.com/grip-unina/B-Free/blob/c6a9f898782fb466b29af01f21960b67415afb0e/code/LICENSE.txt), [TruFor license](https://github.com/grip-unina/TruFor/blob/ae54475df6f41a491d7615100feb19263dec13f7/TruFor_train_test/LICENSE.txt)

Cite Fabrizio Guillaro and colleagues, *A Bias-Free Training Paradigm for More General AI-generated Image Detection*, CVPR 2025, and Fabrizio Guillaro and colleagues, *TruFor: Leveraging All-Round Clues for Trustworthy Image Forgery Detection and Localization*, CVPR 2023, in the report and any public results.
