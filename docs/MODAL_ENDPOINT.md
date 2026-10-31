# Shared B-Free scoring endpoint

## What this is

One authenticated HTTP endpoint that scores a single uploaded image with B-Free on a Modal T4 GPU. It exists so a teammate on Windows can get AI-generation evidence without installing PyTorch, torchvision, timm, or the checkpoint. This is Job B in [MODAL.md](MODAL.md). The local application uses the endpoint only when `BFREE_REMOTE_URL` is set.

## Privacy first

Setting `BFREE_REMOTE_URL` changes where images go. The uploaded image and every processed variant are sent to Modal and leave the machine. Without that variable the local server stays loopback only and no image leaves.

One sentence for a report. When `BFREE_REMOTE_URL` is set, the uploaded image and each transformed variant are sent to a Modal endpoint for AI-generation scoring, and nothing is sent otherwise.

The endpoint receives the variant file bytes with no extra encoding. It decodes them through the same local normalization path, applies no resize, and re-encodes the pixels as PNG before B-Free sees them. The shared secret travels in a request header. The endpoint log records a request id, the status, the device, and the duration. It never records the body, the header values, or the secret.

## Operator setup

Install the Modal client and sign in once.

```bash
python -m pip install modal "fastapi[standard]"
modal token new
```

Create the shared secret under the name the script expects. Pick a long random value and share it with the teammate over a private channel.

```bash
modal secret create bfree-endpoint BFREE_SHARED_SECRET=<long-random-value>
```

Create the weights Volume. The endpoint mounts it read-only at `/models`.

```bash
modal volume create bfree-weights
```

Download the checkpoint archive from the authors, check the published MD5, and unpack it locally as described in [MODEL_SETUP.md](MODEL_SETUP.md). The archive contains a directory named `BFREE_dino2reg4` with `config.yaml` and the file named by `weights_file`.

```bash
curl -fL 'https://www.grip.unina.it/download/prog/B-Free/weights/BFREE_dino2reg4.zip' -o BFREE_dino2reg4.zip
echo "f3f53fa647848b16cf81c913f148a198  BFREE_dino2reg4.zip" | md5sum -c -
mkdir -p weights
unzip BFREE_dino2reg4.zip -d weights
```

Upload the directory to the Volume root. The mount then has `/models/BFREE_dino2reg4/config.yaml` and the checkpoint beside it.

```bash
modal volume put bfree-weights weights/BFREE_dino2reg4 /BFREE_dino2reg4
```

Install `fastapi[standard]` beside Modal on the machine that runs `modal deploy`. The deploy command imports the script locally, and Modal does not provide FastAPI there. The container image installs it too.

The checkpoint must hash to `5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947`. That value was measured by the local CPU adapter run recorded in `output/model-verification/bfree-reference-check.json`. Check it before uploading.

```bash
sha256sum weights/BFREE_dino2reg4/model_epoch_best.pth
```

The container checks the hash again on model load. A mismatch raises an error, and every request then returns 503 instead of a score. The digest is also returned in every successful response.

Deploy the app. Run the command from the repository root so the local `forensics` package is added to the image.

```bash
modal deploy scripts/modal_endpoint.py
```

The command prints the endpoint URL. That URL is the value for `BFREE_REMOTE_URL`. The function clones the B-Free source at revision `c6a9f898782fb466b29af01f21960b67415afb0e` into the image. Weights are never part of the image.

## Fingerprint consequence of the remote branch

The adapter file `forensics/detectors.py` is hashed into `preprocess_sha256` (measured in `forensics/benchmark.py`). Merging the remote scoring branch changed that file, so the recorded value moved from `812f98a6` to `3098d443`. The checkpoint `5948ca78` and the revision `c6a9f89` are unchanged. Recomputing the digest with `6751ede:forensics/detectors.py` as the adapter reproduces `812f98a6` exactly (measured), so the drift is the adapter file alone.

The delivered MPS pilot therefore cannot be resumed with the current adapter. The frozen fingerprint refuses it. The pilot is not broken or invalid. Its outputs are committed and complete, and it is reproduced from `f971d51`, the commit that recorded it. Job A is unaffected because it freezes its own protocol on CUDA. A remote score is a CUDA result with its own fingerprint either way.

## Cost controls

These are configured values, not a billing measurement.

- GPU is `T4`.
- `max_containers=2` caps concurrent containers.
- `timeout=300` caps one request.
- `scaledown_window=300` keeps a warm container for five idle minutes, then stops it.
- There is no schedule and no cron. Nothing runs while nobody calls the endpoint.
- Uploads over 20 MiB are rejected before decoding.

## Teammate setup on Windows

The teammate needs Python 3.12, Git, the base requirements, and this repository. No model packages and no weights are needed.

cmd.exe:

```bat
set BFREE_REMOTE_URL=https://your-endpoint.modal.run
set BFREE_REMOTE_SECRET=the-shared-secret
run.bat
```

PowerShell:

```powershell
$env:BFREE_REMOTE_URL = "https://your-endpoint.modal.run"
$env:BFREE_REMOTE_SECRET = "the-shared-secret"
.\run.bat
```

An optional third value, `BFREE_REMOTE_TIMEOUT`, sets the request timeout in seconds from 1 to 900. The default is 180.

Restart the app after changing any of these values. The launcher keeps inherited variables. If `BFREE_REPO` is also set, the remote branch still wins because it is checked first.

Check the status endpoint after the restart.

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/status
```

`bfree.available` must be true and `bfree.reason` must name the Modal host. The web status panel then reports B-Free ready. The report names the detector `B-Free (remote Modal)`.

## Request and response contract

The local adapter sends raw image bytes. No multipart form and no base64 body.

```http
POST https://your-endpoint.modal.run
Content-Type: application/octet-stream
X-BFree-Secret: <shared secret>
```

A successful response is status 200 with exactly these nine keys, in this order.

```json
{
  "score": 0.9882320210699883,
  "raw_logit": 4.430535316467285,
  "score_kind": "ai_generation",
  "model": "B-Free",
  "model_revision": "c6a9f898782fb466b29af01f21960b67415afb0e",
  "checkpoint_sha256": "5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947",
  "device": "cuda",
  "runtime_seconds": 0.28,
  "calibrated_probability": false
}
```

The score and logit above are published reference values for one B-Free demo image. They show the shape, not a prediction for a new upload. `runtime_seconds` is measured per request. `device` is the container device. `calibrated_probability` is always false because the sigmoid is not a calibrated probability.

Error responses contain only an `error` key.

| Status | Meaning |
|---|---|
| 400 | The body is empty, the Content-Length is malformed, or the bytes are not a supported image |
| 401 | The secret header is missing or wrong. The body is not read |
| 413 | The declared or streamed body is over 20 MiB |
| 500 | The model raised while scoring |
| 503 | The endpoint secret is not configured, or the model could not load |

The local adapter accepts only HTTP 200. Every other status becomes a `DetectorUnavailableError`, as do a timeout, a redirect, a connection failure, an oversized response, malformed JSON, and a contract mismatch. A failed call is an explicit error row with a null score. The analysis writes the exception text into that variant's `error` field and leaves `score` null. Missing inference never becomes zero.

## Secret rotation and turning it off

Rotate the secret with the same name and a new value.

```bash
modal secret create --force bfree-endpoint BFREE_SHARED_SECRET=<new-long-random-value>
modal deploy scripts/modal_endpoint.py
```

Send the new value to the teammate and restart their app. Containers that were already running keep the old value until they scale down, which happens within five idle minutes. A redeploy starts containers with the new value.

To turn remote scoring off, unset `BFREE_REMOTE_URL` and restart the app. Unset means the local path, which is byte-identical to the behavior before this endpoint existed. To stop the app entirely, run `modal app stop ai-image-forensics-bfree`. There is no schedule, so nothing runs while the app is idle.

## Limitations

- Remote scores are not valid for the frozen benchmark protocol. The device changes the detector fingerprint. The frozen pilot used a recorded MPS device and its own run conditions. A CUDA score from this endpoint belongs to a new protocol or to informal evidence, never to the frozen 320-image pilot.
- The sigmoid is bounded but not an independently calibrated probability.
- The endpoint scores one image per request. A local analysis sends one request per variant, so a five-variant run sends five requests.
- The shared secret is the only access control. Anyone who has the URL and the secret can spend the team's credit.
- B-Free is licensed for informational and nonprofit use. The operator hosts the weights and owns that obligation.
- A failed or refused call never produces a substitute score.

## Run log

Measured on 31 October 2026 against
`https://albert2704--ai-image-forensics-bfree-score-endpoint.us-east.modal.run`
on workspace albert2704, Starter plan, gpu T4. Every row below is measured unless
it says otherwise.

| Item | Result | Method |
|---|---|---|
| B-Free checkpoint SHA-256 | `5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947` | Measured earlier by the local CPU adapter and read from `output/model-verification/bfree-reference-check.json`. Not re-measured here. |
| New unit tests | 29 passed | `/home/ubuntu/workspace/AI-Image-Forensics/.venv/bin/python -m unittest tests.test_remote tests.test_modal_endpoint` |
| Full suite | 170 passed, 1 skipped | `/home/ubuntu/workspace/AI-Image-Forensics/.venv/bin/python -m unittest discover -s tests` |
| Adapter and loopback overhead, 32 by 24 PNG, 95 bytes | 0.97 ms median, 0.82 ms min, 1.11 ms max, 25 calls | Local `ThreadingHTTPServer` stub on 127.0.0.1, `time.perf_counter` around `detect()` |
| Adapter and loopback overhead, 1024 by 768 PNG, 4022 bytes | 0.99 ms median, 0.91 ms min, 1.17 ms max, 25 calls | Same stub and timing method |
| Modal deploy end to end, including the image build | 105.9 s | Measured with `modal deploy` |
| Cold POST, correct secret | HTTP 200, 19.00 s total, detector `runtime_seconds` 9.38 | Measured. `runtime_seconds` includes the model load inside the container |
| Warm POST, correct secret | HTTP 200, 2.16 s total, detector `runtime_seconds` 0.498 | Measured on the same container |
| Response body device, revision and checkpoint | `cuda`, `c6a9f898782fb466b29af01f21960b67415afb0e`, `5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947` | Measured in the cold and warm responses |
| Wrong secret | HTTP 401, `{"error":"Unauthorized."}`, 0.79 s | Measured |
| Missing secret | HTTP 401 | Measured |
| Local `/api/status` with `BFREE_REMOTE_URL` set | `bfree.available` true, reason named the Modal host | Measured on the local application |
| Local `/api/status` without `BFREE_REMOTE_URL` | `bfree.available` false, reason named `BFREE_REPO` | Measured on the local application |
| End to end upload, `examples/processing-fixture.png`, rounds 1 | Two variants scored on cuda, 0.4142940989322834 and 0.24485707081394564, no errors | Measured through the local application |
| Direct POST of the same file | 0.4142940989322834, identical to the app pipeline result | Measured. The app pipeline leaves the bytes reaching the detector unchanged |
| Windows cmd.exe and PowerShell setup | could not run | No Windows host is available in this environment |

A GET to the endpoint returns HTTP 405. The body is FastAPI's default
`{"detail":"Method Not Allowed"}`, which is what the deployed app returns
(measured).

The loopback figures bound the local cost of the remote branch. They measure the adapter, JSON validation, and loopback HTTP. They say nothing about network latency or T4 inference time.
