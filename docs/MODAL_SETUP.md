# Setting up Modal from zero

This page installs the three Modal jobs on a machine that has never run them.
It covers the account, the driver environment, the checkpoints, the secrets, the
deploys, the application settings, and what to check when a call fails.

The per-job runbooks stay the reference for how each job behaves.
[MODAL_BATCH.md](MODAL_BATCH.md) covers the GPU replication,
[MODAL_ENDPOINT.md](MODAL_ENDPOINT.md) covers the B-Free endpoint, and
[MODAL_TRUFOR.md](MODAL_TRUFOR.md) covers the regional endpoint. The contract
that binds all three is [MODAL.md](MODAL.md).

None of this replaces the local application. It adds optional remote inference.

## What you end up with

| Job | What it does for you | Endpoint |
|---|---|---|
| A, batch | Scores the 192 test images under nine frozen conditions on a CUDA container | none, it is a command |
| B, B-Free | Scores one upload without installing PyTorch or the checkpoint | one authenticated URL |
| C, TruFor | Produces one manipulation anomaly map, reliability map and overlay | one authenticated URL |

These are the pieces on your side by the end: a Modal workspace with two
volumes, two secrets, two deployed endpoints, and two environment variables in
the application.

## 1. Prerequisites

- A Modal account. The numbers below were measured on the Starter plan, which
  included $30 of monthly compute when the work was done.
- Python 3.12, Git, and this repository.
- Roughly 10 GB of free disk for the checkpoints and the driver environment.

## 2. The driver environment

Use a separate environment. Do not add Modal to the project's model environment,
because a teammate needs the model packages and an operator does not.

```bash
python3.12 -m venv ~/.venvs/modal-driver
~/.venvs/modal-driver/bin/pip install -U pip
~/.venvs/modal-driver/bin/pip install modal numpy Pillow "fastapi[standard]"
```

FastAPI is needed on the operator machine because `modal deploy` imports the
endpoint scripts locally. The container installs its own copy. torch is not
needed here and must not be added, because the batch driver deliberately runs
without it.

## 3. Sign in

```bash
~/.venvs/modal-driver/bin/modal setup
```

This opens a browser flow and writes a token to `~/.modal.toml`. Treat that file
as a credential and keep it at mode `600`. To check what you are signed in as:

```bash
~/.venvs/modal-driver/bin/modal profile current
```

## 4. Checkpoints

The two detectors deliver their weights differently, and the difference is
deliberate.

| Detector | Route | What you do |
|---|---|---|
| B-Free | `modal.Volume` mounted read-only at `/models` | download once, verify, upload once |
| TruFor | downloaded inside the private image at build time | nothing |

TruFor fetches its checkpoint during `modal deploy` and checks both the
published MD5 and a pinned SHA-256, so the operator has no download step. B-Free
keeps the volume route from the original contract, because its terms are
informational and nonprofit and the volume keeps the weights out of any image.
The tradeoff is documented in [MODAL_TRUFOR.md](MODAL_TRUFOR.md) under the
deviation heading.

### B-Free weights

```bash
curl -fL 'https://www.grip.unina.it/download/prog/B-Free/weights/BFREE_dino2reg4.zip' -o external/BFREE_dino2reg4.zip
echo "f3f53fa647848b16cf81c913f148a198  external/BFREE_dino2reg4.zip" | md5sum -c -
mkdir -p external/B-Free/code/weights
unzip external/BFREE_dino2reg4.zip -d external/B-Free/code/weights
sha256sum external/B-Free/code/weights/BFREE_dino2reg4/model_epoch_best.pth
```

The SHA-256 must be `5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947`.
Anything else is not the checkpoint the frozen pilot scored, and the batch job
will refuse it before spending GPU time.

```bash
~/.venvs/modal-driver/bin/modal volume create bfree-weights
~/.venvs/modal-driver/bin/modal volume create ai-forensics-models
~/.venvs/modal-driver/bin/modal volume put bfree-weights \
  external/B-Free/code/weights/BFREE_dino2reg4 /BFREE_dino2reg4
~/.venvs/modal-driver/bin/modal volume put ai-forensics-models \
  external/B-Free/code/weights/BFREE_dino2reg4 /BFREE_dino2reg4
```

Two volumes hold the same 321 MB because each job mounts its own name. Skip one
if you only need one job.

The upload path matters. The zip unpacks to
`external/B-Free/code/weights/BFREE_dino2reg4`, not to `external/BFREE_dino2reg4`.
An upload from the wrong path fails the container's layout check.

## 5. Secrets

Generate a value per endpoint and keep both out of the repository.

```bash
BFREE_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
TRUFOR_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

~/.venvs/modal-driver/bin/modal secret create bfree-endpoint BFREE_SHARED_SECRET="$BFREE_SECRET"
~/.venvs/modal-driver/bin/modal secret create trufor-endpoint TRUFOR_SHARED_SECRET="$TRUFOR_SECRET"
```

`modal secret create --force` overwrites an existing secret, which is how you
rotate one. Rotate and redeploy together, because the container reads the secret
when it starts.

## 6. Deploy

Run both from the repository root, so the local `forensics` package is added to
the image.

```bash
~/.venvs/modal-driver/bin/modal deploy scripts/modal_endpoint.py
~/.venvs/modal-driver/bin/modal deploy scripts/modal_trufor.py
```

Each command prints a URL and a dashboard link. Measured on 31 October 2026,
the B-Free deploy took 105.9 seconds and the TruFor deploy 108.0 seconds,
including a full image build. Later deploys reuse the cached layers and finish
faster unless the image definition changes.

## 7. Point the application at them

Set these before starting the server. All six are optional; unset means local
inference exactly as before.

| Variable | Purpose |
|---|---|
| `BFREE_REMOTE_URL` | B-Free endpoint URL from the deploy output |
| `BFREE_REMOTE_SECRET` | the value you created as `BFREE_SHARED_SECRET` |
| `BFREE_REMOTE_TIMEOUT` | seconds, default 180, range 1 to 900 |
| `TRUFOR_REMOTE_URL` | TruFor endpoint URL from the deploy output |
| `TRUFOR_REMOTE_SECRET` | the value you created as `TRUFOR_SHARED_SECRET` |
| `TRUFOR_REMOTE_TIMEOUT` | seconds, default 1200, range 1 to 3600 |

Linux and macOS:

```bash
export BFREE_REMOTE_URL="https://...modal.run"
export BFREE_REMOTE_SECRET="$BFREE_SECRET"
export TRUFOR_REMOTE_URL="https://...modal.run"
export TRUFOR_REMOTE_SECRET="$TRUFOR_SECRET"
.venv/bin/python -m forensics.server
```

cmd.exe:

```bat
set BFREE_REMOTE_URL=https://...modal.run
set BFREE_REMOTE_SECRET=...
set TRUFOR_REMOTE_URL=https://...modal.run
set TRUFOR_REMOTE_SECRET=...
run.bat
```

Setting a URL without its secret is a configuration error, not a reason to fall
back. The application reports an unavailable detector and names the missing
variable. Leave `BFREE_REPO` unset when using the endpoints; it is only read by
the local path.

## 8. Verify

Open `http://127.0.0.1:8765` and read the status endpoint.

```bash
curl -sS http://127.0.0.1:8765/api/status
```

Both detectors must report `available: true` and their reason must name the
Modal host. A single upload should then return one score per variant, and the
regional button should return a map.

Without the application, check the endpoints directly.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BFREE_REMOTE_URL" \
  -H "X-BFree-Secret: $BFREE_SECRET" --data-binary @examples/processing-fixture.png

curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BFREE_REMOTE_URL" \
  -H "X-BFree-Secret: wrong" --data-binary @examples/processing-fixture.png
```

The first must print `200` and the second `401`. TruFor uses the same checks with
`X-TruFor-Secret`.

Measured on 31 October 2026 against the two deployed endpoints on a T4:

| Call | Time |
|---|---|
| B-Free, cold container, one image | 19.00 s total, 9.38 s inside the detector |
| B-Free, warm, one image | 2.16 s total, 0.498 s inside the detector |
| B-Free, wrong secret | 401 in 0.79 s |
| TruFor, cold container | 19.87 s total, 13.37 s inside TruFor |
| TruFor, warm | 15.59 s total, 10.59 s inside TruFor |
| Full application run, 4 variants, cold | 23.3 s |
| Regional scan from the application | 17.3 s |

Cold means the container had stopped after five idle minutes. Warm means it was
still running.

## 9. Running the batch job

The batch job needs the images locally, because it embeds the 192 test files in
its image.

```bash
.venv/bin/python scripts/acquire_benchmark.py
~/.venvs/modal-driver/bin/python scripts/modal_score.py --smoke --output ~/bfree-modal/smoke.csv
~/.venvs/modal-driver/bin/python scripts/modal_score.py --output ~/bfree-modal/predictions.csv
```

The driver reads `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` from the environment,
not from `~/.modal.toml`. Export both before running.

Measured smoke run on a T4: 9 predictions, 0 failures, 17.27 seconds of scoring,
39.94 seconds elapsed. The full run of 1,728 calls has not been run, so its wall
time stays an estimate in [MODAL_BATCH.md](MODAL_BATCH.md).

## 10. Cost

Measured rates from `modal billing rates` on 31 October 2026: a T4 is
`$0.59/hour`, volumes are `$0.09/GiB/month`, and network egress is `$0.04/GiB`.

What actually drives spend:

- A warm B-Free call bills about half a second of GPU time.
- A TruFor scan bills roughly 10 seconds of GPU time.
- A cold start bills container setup on top, around 14 seconds once.
- Idle containers stop after five idle minutes, so nothing bills while unused.

There is no cron, no warm pool and no recurring deployment in any job. If you
want to raise the idle window to avoid cold starts, edit `scaledown_window` on
the function and redeploy. That trades a cold start for idle billing.

To stop serving, remove the deployments.

```bash
~/.venvs/modal-driver/bin/modal app stop ai-image-forensics-bfree
~/.venvs/modal-driver/bin/modal app stop ai-image-forensics-trufor
```

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Run button is disabled in the page | the adaptive workflow is selected and its planner is not installed | choose the fixed experiment, or install the planner with `scripts/install-planner.py` |
| `401` from an endpoint | the header value does not match the secret | re-read the secret and the environment, then restart the server |
| `503` from an endpoint | the container started without its secret | create the secret, redeploy, restart |
| `413` from an endpoint | the upload is over 20 MiB | resize before sending |
| B-Free reports a fingerprint mismatch | `forensics/detectors.py` changed since the protocol was frozen | expected after the remote branch. Reproduce the pilot from its recorded commit. See the fingerprint note in [MODAL_BATCH.md](MODAL_BATCH.md) |
| The batch refuses the checkpoint | the uploaded weights are not the pilot's | compare against `5948ca78` and re-upload |
| The batch stops on a missing image | `data/benchmark/images` is incomplete | run `scripts/acquire_benchmark.py` |
| `modal deploy` cannot import FastAPI | the operator environment has no FastAPI | install `fastapi[standard]` in the driver environment |
| The regional button returns an error row | the endpoint failed, and the error names the reason | read the app log. The endpoint never returns a substitute map |

## 12. What this guide does not cover

The local planner, Qwen2.5-1.5B-Instruct, is a separate installation and stays
local. Adaptive investigations in the page need it, and the fixed experiment does
not. See [MODEL_SETUP.md](MODEL_SETUP.md).

The Windows launcher is exercised through `run.bat` and documented in
[MODAL_ENDPOINT.md](MODAL_ENDPOINT.md), but the Windows steps have not been run
on a Windows host in this environment.
