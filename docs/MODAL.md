# Running inference on Modal

Modal is used here for three jobs that a laptop and the local VPS cannot do. It
is not the application backend.

**Job A, GPU replication.** Score the 192 test images under the nine frozen
conditions on a CUDA container, then compare point estimates with the delivered
MPS pilot. Delivers `scripts/modal_score.py` and `docs/MODAL_BATCH.md`.

**Job B, shared scoring endpoint.** Expose one authenticated HTTP endpoint so a
teammate on Windows can score a new upload without installing PyTorch or
weights. Delivers `scripts/modal_endpoint.py`, an optional remote detector, and
`docs/MODAL_ENDPOINT.md`.

**Job C, regional endpoint.** Serve TruFor localization for one upload so the
caller needs no PyTorch, no TruFor checkout, and no checkpoint. Delivers
`scripts/modal_trufor.py`, an optional remote regional runner, and
`docs/MODAL_TRUFOR.md`. The image fetches and MD5-checks the checkpoint at build
time.

No job changes a frozen protocol. A CUDA device changes the detector
fingerprint, so Job A freezes its own protocol and reports a new hash.

Setting all three up for the first time is [MODAL_SETUP.md](MODAL_SETUP.md). It
covers the account, the driver environment, the checkpoints, the secrets, the
deploys and the application settings in order.

## Shared contract

Pinned image:

- `python:3.12`
- `torch==2.5.1`, `torchvision==0.20.1`, `timm==1.0.12`, `transformers==4.43.4`,
  `numpy==1.26.4`, `Pillow`, `PyYAML`
- B-Free checkout at `c6a9f898782fb466b29af01f21960b67415afb0e`

Checkpoint handling:

- Weights live in a `modal.Volume`, mounted read-only at `/models`.
- Expected layout is `BFREE_dino2reg4/config.yaml` plus the file named by
  `weights_file` in that config.
- Verify the checkpoint SHA-256 at start and return it in the response. Never
  substitute a different checkpoint.
- Never bake weights into a public image. Their terms are informational and
  nonprofit, and they are not ours to redistribute.

Local image handling:

- Reuse `forensics.pipeline` for decoding and rendering so a condition means the
  same thing locally and remotely.
- Never resize the detector input. B-Free pads internally and handles five
  504-pixel crops itself.

Response shape for a single score. Match the local adapter exactly:

```json
{
  "score": 0.988232,
  "raw_logit": 4.4396,
  "score_kind": "ai_generation",
  "model": "B-Free",
  "model_revision": "c6a9f898782fb466b29af01f21960b67415afb0e",
  "checkpoint_sha256": "<64 hex>",
  "device": "cuda",
  "runtime_seconds": 0.28,
  "calibrated_probability": false
}
```

Batch output columns, identical to the frozen schema:

```
source_id,label,generator,group_id,split,condition,score,raw_logit
```

Missing inference stays missing. A failed call writes an error row, never a zero
and never a guessed score.

## Security and cost rules

- One shared secret header, read from a `modal.Secret`. Reject everything else.
- `max_containers=2` and a per-request image size limit of 20 MiB.
- No public endpoint without the secret. A leaked URL spends the team's credit.
- Do not enable a cron schedule. Nothing should run unattended.
- Log a request id and the device for each call. Never log image bytes.

## Ownership

Job A owns `scripts/modal_score.py`, `docs/MODAL_BATCH.md`, and its tests.

Job B owns `scripts/modal_endpoint.py`, `forensics/remote.py`, its tests, and
`docs/MODAL_ENDPOINT.md`. Job B may edit `forensics/detectors.py` only to add an
optional remote branch, guarded so the default stays local.

Neither job edits `README.md`, `requirements-models.txt`, the frozen outputs, or
the platform documents. The coordinator folds results into those.

## Acceptance

Job A is done when a dry run without a Modal token fails with a clear message,
the pinned image builds, and a smoke run scores one image through the frozen
pipeline and prints the schema above. It must also document the command to run
all nine conditions and the expected wall time.

Job B is done when the endpoint rejects a request without the secret, returns the
schema above for a real image, and the local application can opt into it with
`BFREE_REMOTE_URL` set. Unset, behaviour is byte-identical to today. Its tests
cover the rejected request, a valid response, and the unset fallback.

Both jobs report measured timings, not estimates, in their pull request.
