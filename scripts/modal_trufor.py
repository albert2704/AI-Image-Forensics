"""Authenticated regional localization on Modal.

TruFor runs from the image, the checkpoint is fetched and MD5-checked during the
image build, and the request core stays importable without modal, fastapi, or
torch.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import AsyncIterator, Callable
import uuid

try:
    import modal
except ModuleNotFoundError:
    modal = None

from forensics.detectors import TRUFOR_REVIEWED_REVISION, DetectorUnavailableError, _revision
from forensics.pipeline import MAX_BYTES, decode_image, encode
from forensics.remote_regional import (
    ARTIFACT_NAMES_BY_KEY,
    MODEL_NAME,
    REGIONAL_PREDICTION_KEYS,
    SECRET_HEADER,
)


MAX_UPLOAD_BYTES = MAX_BYTES
SECRET_ENV = "TRUFOR_SHARED_SECRET"
SECRET_NAME = "trufor-endpoint"
APP_NAME = "ai-image-forensics-trufor"
TRUFOR_REPO = Path("/opt/TruFor")
WEIGHTS_URL = "https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip"
WEIGHTS_ZIP_MD5 = "7bee48f3476c75616c3c5721ab256ff8"
# The tar inside that zip. Pinning it means a rebuilt image cannot silently
# swap the checkpoint even if the download host changes.
CHECKPOINT_SHA256 = "ac1d90e329a72e0d66e8665e123a19e94bfae3209c3ef8a4f9ca3b91578c7844"
WEIGHTS_ZIP = "/tmp/TruFor_weights.zip"
CHECKPOINT = Path("TruFor_train_test") / "pretrained_models" / "trufor.pth.tar"

app = None


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict


def _matches(presented: str | None, expected: str) -> bool:
    try:
        return bool(presented) and hmac.compare_digest(presented.encode("ascii"), expected.encode("ascii"))
    except (AttributeError, UnicodeError):
        return False


def _response_body(raw: dict) -> dict:
    body = {}
    for key in REGIONAL_PREDICTION_KEYS:
        if key in ARTIFACT_NAMES_BY_KEY:
            body[key] = base64.b64encode(Path(raw[f"{key.removesuffix('_base64')}_path"]).read_bytes()).decode("ascii")
        elif key == "model":
            body[key] = MODEL_NAME
        else:
            body[key] = raw[key]
    return body


async def handle_regional_request(
    *,
    presented_secret: str | None,
    content_length: str | None,
    chunks: AsyncIterator[bytes],
    expected_secret: str | None,
    run_runner: Callable[[Path, Path], dict],
) -> Reply:
    request_id = uuid.uuid4().hex
    device = None
    received = 0

    def finish(status: int, body: dict, error: str | None = None) -> Reply:
        entry = {"request_id": request_id, "status": status, "device": device, "bytes": received}
        if error is not None:
            entry["error"] = error
        print(json.dumps(entry), flush=True)
        return Reply(status=status, body=body)

    if not expected_secret:
        return finish(503, {"error": "Endpoint secret is not configured."})
    if not _matches(presented_secret, expected_secret):
        return finish(401, {"error": "Unauthorized."})
    if content_length is not None:
        if not (isinstance(content_length, str) and content_length.isascii() and content_length.isdigit()):
            return finish(400, {"error": "Invalid Content-Length."})
        try:
            declared = int(content_length)
        except ValueError:
            return finish(400, {"error": "Invalid Content-Length."})
        if declared > MAX_UPLOAD_BYTES:
            return finish(413, {"error": "Image exceeds the 20 MiB limit."})
    data = bytearray()
    async for chunk in chunks:
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            received = len(data)
            return finish(413, {"error": "Image exceeds the 20 MiB limit."})
    received = len(data)
    if not data:
        return finish(400, {"error": "The request body is empty."})
    try:
        image, _ = decode_image(bytes(data))
    except ValueError as exc:
        return finish(400, {"error": str(exc)})
    received_sha256 = hashlib.sha256(bytes(data)).hexdigest()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "input.png"
        # Same normalization the local path feeds TruFor, so a JPEG upload and a
        # PNG upload of the same pixels reach the detector identically.
        source.write_bytes(encode(image, "PNG"))
        try:
            body = _response_body(run_runner(source, root))
        except Exception as exc:
            return finish(500, {"error": "Regional inference failed."}, type(exc).__name__)
        body["input_sha256"] = received_sha256
    device = body["device"]
    return finish(200, body)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_layout(repo: Path) -> str:
    root = Path(repo)
    if not (root / "TruFor_train_test" / "test.py").is_file():
        raise DetectorUnavailableError("TruFor test.py is missing from the image.")
    checkpoint = root / CHECKPOINT
    if not checkpoint.is_file():
        raise DetectorUnavailableError("TruFor checkpoint is missing from the image.")
    revision = _revision(root)
    if revision != TRUFOR_REVIEWED_REVISION:
        raise DetectorUnavailableError(f"TruFor checkout is at {revision}, not the reviewed revision.")
    digest = sha256_file(checkpoint)
    if digest != CHECKPOINT_SHA256:
        raise DetectorUnavailableError(f"TruFor checkpoint is {digest}, not the pinned {CHECKPOINT_SHA256}.")
    return digest


def build_run_runner() -> Callable[[Path, Path], dict]:
    def run(image_path: Path, output_dir: Path) -> dict:
        from forensics.detectors import run_trufor

        return run_trufor(image_path, output_dir, TRUFOR_REPO, sys.executable, "cuda")

    return run


_RUNNER = None
_RUNNER_LOCK = threading.Lock()


def run_regional(image_path: Path, output_dir: Path) -> dict:
    """Check the image layout on the first inference request, then reuse it."""
    global _RUNNER
    if _RUNNER is None:
        with _RUNNER_LOCK:
            if _RUNNER is None:
                verify_layout(TRUFOR_REPO)
                _RUNNER = build_run_runner()
    return _RUNNER(image_path, output_dir)


if modal is not None:
    try:
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except ModuleNotFoundError as exc:
        # modal deploy imports this module on the operator machine, where modal
        # provides no FastAPI. The container image installs it.
        raise ModuleNotFoundError(
            "The endpoint script needs fastapi on the deploying machine. "
            "Run: python -m pip install 'fastapi[standard]'"
        ) from exc

    app = modal.App(APP_NAME)
    # Read once when the container imports the module. An empty value makes
    # every request a 503.
    expected_secret = os.environ.get(SECRET_ENV)
    image = (
        modal.Image.from_registry("python:3.12", add_python="3.12")
        .apt_install("git", "curl", "unzip")
        .pip_install(
            "torch==2.5.1", "torchvision==0.20.1", "timm==1.0.12", "transformers==4.43.4",
            "numpy==1.26.4", "Pillow", "PyYAML", "yacs", "matplotlib==3.9.2", "fastapi[standard]",
        )
        .run_commands(
            f"git clone https://github.com/grip-unina/TruFor.git {TRUFOR_REPO}",
            f"git -C {TRUFOR_REPO} checkout {TRUFOR_REVIEWED_REVISION}",
            f"curl -fL {WEIGHTS_URL} -o {WEIGHTS_ZIP}",
            f'echo "{WEIGHTS_ZIP_MD5}  {WEIGHTS_ZIP}" | md5sum -c -',
            f"unzip -q {WEIGHTS_ZIP} -d {TRUFOR_REPO}/TruFor_train_test/pretrained_models",
            f"mv {TRUFOR_REPO}/TruFor_train_test/pretrained_models/weights/trufor.pth.tar "
            f"{TRUFOR_REPO}/{CHECKPOINT}",
            f"rm -f {WEIGHTS_ZIP}",
        )
        .add_local_python_source("forensics")
    )

    @app.function(
        image=image,
        gpu="T4",
        max_containers=2,
        min_containers=0,
        timeout=900,
        scaledown_window=300,
        secrets=[modal.Secret.from_name(SECRET_NAME, required_keys=[SECRET_ENV])],
    )
    @modal.fastapi_endpoint(method="POST")
    async def regional_endpoint(request: Request):
        reply = await handle_regional_request(
            presented_secret=request.headers.get(SECRET_HEADER.lower()),
            content_length=request.headers.get("content-length"),
            chunks=request.stream(),
            expected_secret=expected_secret,
            run_runner=run_regional,
        )
        return JSONResponse(status_code=reply.status, content=reply.body)
