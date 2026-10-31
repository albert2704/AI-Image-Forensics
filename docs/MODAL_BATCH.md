# B-Free batch on Modal

Job A from [MODAL.md](MODAL.md). This runs the delivered 192-image test split
under the nine frozen conditions on a CUDA container and writes the frozen
prediction schema, so the team can compare point estimates with the MPS pilot in
`output/benchmark/results/bfree/predictions.csv`.

The runner scores one image-and-condition pair per Modal call and fans out 1,728
calls with `.map()`. Rendering is `forensics.benchmark.render_condition`, so a
condition means the same thing here and in the pilot. The detector is the
installed `BFreeDetector` with native preprocessing. It does not resize the
detector input; B-Free pads internally and uses its five 504-pixel crops.

## Before the first run

The delivered dataset must be present. `data/benchmark/manifest.csv` lists 320
sources and `data/benchmark/images/` holds them. The runner reads only the 192
test rows and verifies each image's SHA-256 against the manifest. A missing image
or a changed checksum stops the run before any container starts.

Weights live in a Modal Volume, never in the image. Create it once and upload the
delivered checkpoint directory:

```bash
modal volume create ai-forensics-models
modal volume put ai-forensics-models external/BFREE_dino2reg4 /BFREE_dino2reg4
```

The mounted layout must be `/models/BFREE_dino2reg4/config.yaml` plus the file
named by `weights_file` in that config. The volume is mounted read-only. The
runner probes it with one real inference before any fan-out, prints the
checkpoint SHA-256, the model revision, the GPU name and the Torch and CUDA
versions, and compares the checkpoint with the pilot's. A different checkpoint
stops the run before a single study call, so it can never produce a CSV that
looks comparable.

Modal credentials come from the environment, not from a `modal.Secret`. Without
them the runner exits before importing Modal:

```bash
modal setup   # or: modal token new
export MODAL_TOKEN_ID=...      # values are in ~/.modal.toml after setup
export MODAL_TOKEN_SECRET=...
```

The driver process needs the Modal SDK plus NumPy and Pillow. Do not add Modal to
the project's model environment; use a separate one:

```bash
python3.12 -m venv ~/.venvs/modal-driver
~/.venvs/modal-driver/bin/pip install modal numpy Pillow
```

The container's own dependencies are pinned in `scripts/modal_score.py` and are
independent of this driver environment.

## Commands

Run from the repository root.

One smoke image, all nine conditions, nine calls:

```bash
~/.venvs/modal-driver/bin/python scripts/modal_score.py --smoke \
  --output ~/bfree-modal/smoke.csv
```

The full batch, 192 images × 9 conditions, 1,728 calls:

```bash
~/.venvs/modal-driver/bin/python scripts/modal_score.py \
  --output ~/bfree-modal/predictions.csv
```

`--output` is required and should stay outside `output/`; this job does not own
that tree. The smoke run prints each detector response, including the single-score
schema from MODAL.md. Both runs print the probe result and a final counts summary.

The test images for the selected tasks are added to the private image under
`/data` at build time. The smoke image carries one image and builds quickly. The
full run uploads the 192 test images once, about 326 MiB, and reuses that cached
layer on later runs.

## Outputs

Three files next to `--output`:

| File | Contents |
|---|---|
| `predictions.csv` | The frozen columns `source_id,label,generator,group_id,split,condition,score,raw_logit`, sorted by source and condition |
| `predictions.meta.json` | Device, GPU, Torch and CUDA versions, checkpoint SHA-256, detector fingerprint, run identity hash, model revision, manifest hash, condition recipes, counts, measured elapsed and scoring seconds, per-call inference distribution |
| `predictions.failures.jsonl` | One record per failed call, with `source_id`, `condition`, `error_type` and `error`. Empty when every call succeeds |

A failed call never becomes a zero and never becomes a guessed score. It is
absent from `predictions.csv`, present in the failures file, and the process
exits 1. There is no cache and no resume in this runner; a rerun recomputes every
call and replaces all three files.

The meta file's `run_sha256` identifies this batch by manifest hash, condition
recipes, source checksums and the CUDA detector fingerprint. It is not the frozen
`protocol.json` hash and must never be used to resume the pilot's protocol.
This runner does not write a new `protocol.json`; it reports the identity inputs
so the coordinator can fold the CUDA run in without mixing it with the MPS
study.

## Expected wall time

The only measured anchor is the MPS pilot's own journal,
`output/benchmark/results/bfree/predictions.jsonl`, which records 1,728 calls and
1,243.2 seconds of detector time, with a median of 0.707 s and a maximum of
4.108 s per call on MPS.

CUDA time on a T4 was not measured here. There was no Modal token, GPU or
delivered image set in the checkout where this document was written. The
following are guesses built from that anchor and must not be read as a
measurement:

| Step | Estimate | Basis |
|---|---|---|
| 1,728 calls, 2 containers | 3 to 10 minutes | 864 calls per container; 0.2 to 0.7 s per call. The upper bound assumes no speedup over the 0.707 s measured MPS median |
| First image build | 5 to 15 minutes | Torch and CUDA wheels, the B-Free clone at the pinned revision, and the 326 MiB test-image layer. Unmeasured |
| Container start and model load | about 30 seconds per container | Unmeasured |
| First full run, end to end | 10 to 25 minutes | Sum of the rows above |
| Later full run with the image cached | 4 to 12 minutes | Same call estimate plus container start |

Measure them again on the first real run; `predictions.meta.json` records the wall
time and the per-call distribution for that run.

## Comparing with the MPS pilot

`output/benchmark/results/bfree/predictions.csv` is the frozen MPS pilot. It has
eleven columns; this runner writes the eight frozen ones. Join on
`(source_id, condition)` and never concatenate the files.

Check these before comparing point estimates:

1. `predictions.meta.json` reports `predictions: 1728`, `sources: 192` and
   `failures: 0`. A short CSV describes the available cases, not the intended
   study.
2. `checkpoint_sha256` matches the pilot's `5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947`.
   The runner refuses to score when it differs. A different checkpoint makes the
   comparison invalid, not merely noisy.
3. The condition recipes in the meta file match
   [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md). The script refuses any set
   other than the nine frozen names and recipes.

Then compare per condition. Use the frozen decision `score > 0.5` and the
primary contrast `baseline` to `jpeg_q85_r3`. Report balanced accuracy per
condition on the same 192 sources, and inspect per-source score deltas rather
than only aggregates. MPS and CUDA run the same math but not the same kernels;
the repository's CPU and MPS check recorded a maximum absolute logit difference
of 0.000035, so expect small differences, not identical bytes. A large shift
points at a different checkpoint, a different B-Free revision or a rendering
difference, and should be investigated before any scientific claim.

The pilot is a frozen study on MPS. This batch is a device replication with its
own fingerprint, so do not append its rows to the pilot's journal or resume the
pilot's protocol with it. Compare the derived CSV.

## Limits

- Two containers at most. No cron schedule and no public endpoint.
- No cache between runs and no partial resume. Every run is a fresh measurement.
- The nine recipes are replicated from `forensics.benchmark.DEFAULT_CONDITIONS`
  and pinned by a test against `output/benchmark/protocol.json`.
- The image build, the smoke run and the full 1,728-call run were not executed
  while writing this document. There was no Modal token, no CUDA device and no
  delivered image set in this checkout. The commands and estimates above are
  therefore unverified on Modal.
