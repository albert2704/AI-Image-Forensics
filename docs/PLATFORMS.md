# Running on macOS, Linux and Windows

The application is plain Python 3.12 plus a browser. Only the optional model
inference needs platform-specific setup, because PyTorch wheels and device names
differ. This page covers what runs where, and what has to be installed.

## What is and is not in this repository

| Path | In git | Why |
|---|---|---|
| `forensics/`, `web/`, `scripts/`, `tests/` | yes | application and tooling |
| `output/benchmark/`, `output/agent-evaluation/` | yes | frozen predictions, summaries, figures |
| `output/model-verification/` | yes | the read-only demo with real recorded scores |
| `data/benchmark/manifest.csv` and metadata | yes | selection plan, hashes, licences |
| `data/benchmark/images/` | **no** | Synthbuster/RAISE terms; re-download with `scripts/acquire_benchmark.py` |
| `external/` | **no** | third-party model code and checkpoints, hundreds of MB to ~3 GB |
| `.venv/` | **no** | machine-specific binaries; recreate with `scripts/bootstrap.sh` |
| `output/runs/` | **no** | per-session uploads and derivatives |

`python scripts/doctor.py` reports which of these are present and what each
missing piece blocks. Run it first on any machine.

## Support matrix

| | macOS (Apple Silicon) | Linux | Windows 10/11 |
|---|---|---|---|
| Dashboard, transformations, MSE/PSNR, exports | verified | supported | supported |
| Committed demo with recorded scores | verified | supported | supported |
| 79-feature FFT/DCT baseline | verified | supported | supported |
| B-Free inference | verified (MPS) | CPU or CUDA | CPU or CUDA |
| TruFor regional scan | verified (CPU) | CPU or CUDA | CPU or CUDA |
| Qwen planner | verified (MPS/CPU) | CPU | CPU |
| Study harness (`forensics.benchmark`, `forensics.breakpoint`) | verified | supported | supported |
| Resume the delivered frozen protocol | **only here** | fingerprint mismatch | fingerprint mismatch |

"Fingerprint mismatch" is deliberate: the frozen protocol records the device and
package versions alongside the checkpoint hash (`forensics/benchmark.py`), and
the delivered pilot froze `BFREE_DEVICE=mps`. Other hosts can run the same code,
but they start a new study with a new protocol hash rather than appending to that
journal. Verify the delivered numbers from the committed `predictions.csv`
instead of re-running inference.

## Quick start — base workflow, no models

Every host needs Python 3.12 and Git. Scores stay missing until a checkpoint is
installed; image processing and measurements are still real.

**macOS / Linux**

```bash
git clone <repo> && cd AI-Image-Forensics
bash scripts/bootstrap.sh
.venv/bin/python -m forensics.server      # http://127.0.0.1:8765
```

**Windows (PowerShell)**

```powershell
git clone <repo>; cd AI-Image-Forensics
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
.\run.bat                                  # http://127.0.0.1:8765
```

`run.bat` sets `PYTHONUTF8=1`, which avoids `UnicodeEncodeError` when the
console code page cannot encode Vietnamese output.

## Installing the detectors

Upstream sources, revisions, checksums and the exact verified commands live in
[MODEL_SETUP.md](MODEL_SETUP.md). The pins are also packaged as an installable
file:

```bash
.venv/bin/python -m pip install -r requirements-models.txt      # macOS/Linux
.\.venv\Scripts\python.exe -m pip install -r requirements-models.txt   # Windows
```

### Linux

```bash
bash scripts/bootstrap.sh --models
mkdir -p external
git clone https://github.com/grip-unina/B-Free.git external/B-Free
git -C external/B-Free checkout c6a9f898782fb466b29af01f21960b67415afb0e

curl -fL https://www.grip.unina.it/download/prog/B-Free/weights/BFREE_dino2reg4.zip \
  -o external/BFREE_dino2reg4.zip
echo "f3f53fa647848b16cf81c913f148a198  external/BFREE_dino2reg4.zip" | md5sum -c -
unzip external/BFREE_dino2reg4.zip -d external/B-Free/code/weights

source scripts/model-env.sh
export BFREE_DEVICE=cpu        # or cuda
.venv/bin/python scripts/doctor.py
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -Models
New-Item -ItemType Directory -Force external | Out-Null
git clone https://github.com/grip-unina/B-Free.git external\B-Free
git -C external\B-Free checkout c6a9f898782fb466b29af01f21960b67415afb0e

curl.exe -fL "https://www.grip.unina.it/download/prog/B-Free/weights/BFREE_dino2reg4.zip" `
  -o external\BFREE_dino2reg4.zip
if ((Get-FileHash external\BFREE_dino2reg4.zip -Algorithm MD5).Hash -ne "F3F53FA647848B16CF81C913F148A198") {
    throw "Checkpoint checksum mismatch"
}
Expand-Archive external\BFREE_dino2reg4.zip -DestinationPath external\B-Free\code\weights

. .\scripts\model-env.ps1
$env:BFREE_DEVICE = "cpu"      # or "cuda"
.\.venv\Scripts\python.exe scripts\doctor.py
```

TruFor follows the same pattern with revision `ae54475d…`; see
[MODEL_SETUP.md](MODEL_SETUP.md). The optional planner installs with
`python scripts/install-planner.py` on any host.

## Device names

| Device | B-Free | TruFor | Notes |
|---|---|---|---|
| `cpu` | yes | yes | default in the interactive launcher; slowest |
| `cuda`, `cuda:N` | yes | yes | install the CUDA PyTorch wheel first |
| `mps` | yes | **no** | Apple Silicon only; TruFor's CLI exposes no MPS path |

The measured pilot ran B-Free at roughly 0.7 s per call on MPS. Expect several
seconds per call on desktop CPU, so a full 1,728-call test pass is an overnight
job rather than an afternoon one.

## Platform notes

- **Study-directory locking** uses `flock` on POSIX and `msvcrt.locking` on
  Windows, so `forensics.benchmark` and `forensics.breakpoint` refuse concurrent
  writers on both.
- **Served content types** are explicit for `.js`, `.css`, `.html`, `.json` and
  images. Windows resolves those through the registry, where `.js` can come back
  as `text/plain`; combined with `X-Content-Type-Options: nosniff` that would
  stop the browser executing the application.
- **Paths** are built with `pathlib`, so forward and back slashes both work. Keep
  the checkout shallow; very deep paths can exceed the Windows limit.
- **Line endings** are normalized by `.gitattributes`; run the shell scripts with
  `bash` on Windows/WSL rather than `cmd`.

## What "reproduce" means off the original machine

| Goal | What to do |
|---|---|
| Verify the reported numbers | Read `output/benchmark/results/*/predictions.csv`; re-run the analyses |
| See the interface with real scores | Open the committed demo; no weights needed |
| Run the pipeline on new images | Install B-Free; `cpu` or `cuda` |
| Re-execute the frozen pilot | Requires the original Mac, MPS and the recorded pins |
| Extend or repeat the study | Freeze a new protocol on your host; it gets its own hash |
