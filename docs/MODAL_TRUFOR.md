# Shared TruFor regional endpoint

## What this is

One authenticated HTTP endpoint that runs TruFor localization for a single uploaded image on a Modal T4 GPU. It exists so a caller needs no PyTorch, no TruFor checkout, and no checkpoint. This is Job C in [MODAL.md](MODAL.md). The local application uses the endpoint only when `TRUFOR_REMOTE_URL` is set.

## Privacy first

Setting `TRUFOR_REMOTE_URL` changes where images go. The uploaded image is sent to Modal and leaves the machine. Without that variable the local server stays loopback only and no image leaves.

One sentence for a report. When `TRUFOR_REMOTE_URL` is set, the uploaded image is sent to a Modal endpoint for regional manipulation evidence, and nothing is sent otherwise.

The endpoint receives the file bytes with no extra encoding and writes them verbatim to a temporary file, so the hash the caller computes is the hash TruFor records. It runs the same `run_trufor` adapter the local path uses. The three PNG artifacts come back inline as base64. The shared secret travels in a request header. The endpoint log records a request id, the status, the device, and the byte count. It never records the body, the filename, or the secret.

## Operator setup

Install the Modal client and sign in once.

```bash
python -m pip install modal "fastapi[standard]"
modal token new
```

Create the shared secret under the name the script expects. Pick a long random value.

```bash
modal secret create trufor-endpoint TRUFOR_SHARED_SECRET=<long-random-value>
```

Deploy from the repository root so the local `forensics` package is added to the image.

```bash
modal deploy scripts/modal_trufor.py
```

The command prints the endpoint URL. That URL is the value for `TRUFOR_REMOTE_URL`. These four commands are the whole operator setup. There is no volume, no manual download, and no upload step.

## Weights at image build

The image does the download, so the operator never does. During `modal deploy` the image:

- clones `https://github.com/grip-unina/TruFor.git` into `/opt/TruFor` and checks out `ae54475df6f41a491d7615100feb19263dec13f7`
- downloads `https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip`
- checks the archive MD5 against `7bee48f3476c75616c3c5721ab256ff8`, the value published for the local install in [MODEL_SETUP.md](MODEL_SETUP.md)
- unzips it into `TruFor_train_test/pretrained_models`
- moves `weights/trufor.pth.tar` up to `pretrained_models/trufor.pth.tar`, because the official archive contains a `weights/` subdirectory
- deletes the archive

A failed clone, checkout, download, checksum, or move fails the build. Nothing deploys with a different checkpoint. The first inference request in each container also checks that the checkout is at the reviewed revision and that the checkpoint is present. Every response carries the checkpoint SHA-256 as `checkpoint_sha256`.

## Deviation from the shared Modal contract

[MODAL.md](MODAL.md) says weights live in a Modal Volume, mounted read-only, and never in an image. This job bakes the checkpoint into a private image instead. The reason is the operating requirement that the operator runs `modal deploy` and nothing else. A Volume would add a manual download, a local MD5 check, and `modal volume put` before the first deploy. The image is private to the workspace and the checkpoint is never pushed to a public registry. The Volume route is the alternative if the team later wants one shared copy. Create `modal volume create trufor-weights`, upload the same `weights/` directory, mount it read-only at `/models`, and drop the fetch commands from the image.

## Local opt-in

Set two variables and restart the application.

cmd.exe:

```bat
set TRUFOR_REMOTE_URL=https://your-endpoint.modal.run
set TRUFOR_REMOTE_SECRET=the-shared-secret
run.bat
```

PowerShell:

```powershell
$env:TRUFOR_REMOTE_URL = "https://your-endpoint.modal.run"
$env:TRUFOR_REMOTE_SECRET = "the-shared-secret"
.\run.bat
```

An optional third value, `TRUFOR_REMOTE_TIMEOUT`, sets the request timeout in seconds from 1 to 3600. The default is 1200.

Check the status endpoint after the restart.

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/status
```

`trufor.available` must be true and `trufor.reason` must name the Modal host. While `TRUFOR_REMOTE_URL` is set, `TRUFOR_REPO` is ignored. The web status panel then reports TruFor ready. The report names the detector `TruFor (remote Modal)` and stores the published artifacts as `regional-heatmap.png`, `regional-reliability.png`, and `regional-overlay.png` under the run.

Unset `TRUFOR_REMOTE_URL` to run TruFor locally again. Unset means the previous local path, byte for byte. A misconfigured URL or secret does not fall back. It reports `TruFor remote scoring is misconfigured` with the reason.

## Request and response contract

The local adapter sends raw image bytes. No multipart form and no base64 body.

```http
POST https://your-endpoint.modal.run
Content-Type: application/octet-stream
X-TruFor-Secret: <shared secret>
```

A curl call from any machine that has the URL and the secret:

```bash
curl -fS -X POST "$TRUFOR_REMOTE_URL" \
  -H "Content-Type: application/octet-stream" \
  -H "X-TruFor-Secret: $TRUFOR_REMOTE_SECRET" \
  --data-binary @image.png
```

The same request from inside a Modal container, for an operator who wants to check the endpoint without a local copy of TruFor:

```bash
modal shell scripts/modal_trufor.py::regional_endpoint
curl -fS -X POST "https://your-endpoint.modal.run" \
  -H "Content-Type: application/octet-stream" \
  -H "X-TruFor-Secret: <shared secret>" \
  --data-binary @/opt/TruFor/test_docker/images/tampered2.png
```

The image contains the TruFor checkout and its test images, so no local file is needed.

A successful response is status 200 with exactly these 21 keys, in this order.

```json
{
  "status": "complete",
  "message": "TruFor generated a manipulation anomaly map and localization reliability map. Output dimensions and numeric ranges were checked.",
  "warnings": [
    "TruFor localizes manipulation anomalies; it does not identify AI-generated pixels.",
    "The displayed score is not an independently calibrated probability."
  ],
  "model": "TruFor (remote Modal)",
  "model_revision": "ae54475df6f41a491d7615100feb19263dec13f7",
  "checkpoint_sha256": "<64 hex>",
  "score": 0.0322388,
  "score_kind": "local_manipulation",
  "input_sha256": "<64 hex>",
  "calibrated_probability": false,
  "device": "cuda",
  "runtime_seconds": 1.0,
  "imgsize": [768, 1024],
  "heatmap_kind": "local_manipulation_anomaly",
  "heatmap_range": [0, 1],
  "heatmap_legend": "Fixed scale: blue 0 → cyan → yellow → red 1; higher values indicate stronger manipulation anomalies.",
  "reliability_legend": "Black 0 → white 1; lighter pixels indicate greater estimated localization reliability.",
  "reliability_mean": 0.61,
  "heatmap_base64": "<PNG bytes>",
  "reliability_base64": "<PNG bytes>",
  "overlay_base64": "<PNG bytes>"
}
```

The score is the published local reference value for one official TruFor example, not a prediction for a new upload. `runtime_seconds`, `imgsize`, and `reliability_mean` above show the shape. `imgsize` is `[height, width]` and matches all three PNGs. `device` is the container device. `calibrated_probability` is always false. `input_sha256` is the hash of the bytes the caller sent. The caller checks that hash, the revision, the device, the score range, and every PNG dimension before it writes a file. A response that disagrees is refused in full.

Error responses contain only an `error` key.

| Status | Meaning |
|---|---|
| 400 | The body is empty, the Content-Length is malformed, or the bytes are not a supported image |
| 401 | The secret header is missing or wrong. The body is not read |
| 413 | The declared or streamed body is over 20 MiB |
| 500 | The inference runner raised, or its result did not match the contract. The response does not repeat the exception text |
| 503 | The endpoint secret is not configured |

The local adapter accepts only HTTP 200. Every other status becomes a `DetectorUnavailableError`, as do a timeout, a redirect, a connection failure, an oversized response, malformed JSON, and a contract mismatch. A failed call writes a regional record with status `error` and the exception text. It never writes a score and never writes a partial artifact set.

## Timeouts and cost

The timeout chain is client 1200 seconds, container 900 seconds, CLI 600 seconds. Each limit sits above the next one on purpose. `run_trufor` gives its TruFor subprocess 600 seconds. The container gets 900 so model load and the three PNG renders fit, and so the container answers with its own error instead of being killed while it is still working. The client gets 1200 so it does not abandon a slow call before the container's limit fires, which keeps the failure attributable to the model rather than to the caller's socket.

These are configured values, not a billing measurement.

- GPU is `T4`.
- `max_containers=2` caps concurrent containers.
- `min_containers=0` means no container is kept warm when nobody calls.
- `timeout=900` caps one request.
- `scaledown_window=300` keeps a warm container for five idle minutes, then stops it.
- There is no schedule and no cron. Nothing runs while nobody calls the endpoint.
- Uploads over 20 MiB are rejected before decoding.

Cost is an estimate to be measured. A T4 container is billed while a request runs and for the five idle minutes after it. No request has run against a deployed copy of this endpoint from this worktree, so no dollar figure is stated. Read the first week from the Modal dashboard and record it here.

## Secret rotation and turning it off

Rotate the secret with the same name and a new value.

```bash
modal secret create --force trufor-endpoint TRUFOR_SHARED_SECRET=<new-long-random-value>
modal deploy scripts/modal_trufor.py
```

Send the new value to every caller and restart their app. Running containers keep the old value until they scale down, within five idle minutes. A redeploy starts containers with the new value.

To turn remote regional inference off, unset `TRUFOR_REMOTE_URL` and restart the app. To stop the app entirely, run `modal app stop ai-image-forensics-trufor`.

## Limitations

- Remote scores are not valid for the frozen benchmark protocol. The device changes the detector fingerprint. A CUDA result belongs to a new protocol or to informal evidence, never to the frozen pilot.
- TruFor localizes manipulation anomalies. It does not identify AI-generated pixels.
- The score is bounded and not an independently calibrated probability.
- The endpoint runs one image per request.
- The shared secret is the only access control. Anyone who has the URL and the secret can spend the team's credit.
- The operator hosts the checkpoint and owns its terms.
- A failed or refused call never produces a substitute score.

## Run log

Measured on 31 October 2026 in the implementation worktree.

| Item | Result | Method |
|---|---|---|
| New client and endpoint tests | 34 passed | `.venv/bin/python -m unittest tests.test_remote_regional tests.test_modal_trufor` |
| Server branch tests | 17 passed in `tests.test_server`, 6 of them new | `.venv/bin/python -m unittest tests.test_server` |
| Full suite | 207 tests, 1 skipped | `.venv/bin/python -m unittest discover -s tests` |
| Modal image build | could not run | The modal package and CLI are not installed here, no Modal credentials are present, and deploys are out of scope for this change |
| T4 inference over the public endpoint | could not run | No deploy exists and there are no Modal credentials |
| Public endpoint 401, 413, and 200 responses | could not run | No deploy exists and there are no Modal credentials |
| Windows cmd.exe and PowerShell setup | could not run | No Windows host is available in this environment |

The loopback tests in `tests/test_remote_regional.py` and `tests/test_server.py` cover the client, the endpoint core, and the server branch through a real local HTTP round trip. They say nothing about network latency or T4 inference time.
