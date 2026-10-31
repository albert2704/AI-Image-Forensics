"""Authenticated single-image scoring on Modal.

B-Free runs from the image, the checkpoint comes from a read-only Volume, and
the request core stays importable without modal, fastapi, or torch.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import AsyncIterator, Callable
import uuid

try:
    import modal
except ModuleNotFoundError:
    modal = None

from forensics.detectors import BFREE_REVIEWED_REVISION, BFreeDetector, DetectorUnavailableError
from forensics.pipeline import MAX_BYTES, decode_image, encode
from forensics.remote import BFREE_CHECKPOINT_SHA256, ERROR_PREFIX, SECRET_HEADER, validate_prediction


MAX_UPLOAD_BYTES = MAX_BYTES
SECRET_ENV = "BFREE_SHARED_SECRET"
MODELS_DIR = Path("/models")
WEIGHTS_DIR = MODELS_DIR / "BFREE_dino2reg4"
BFREE_REPO = Path("/opt/B-Free")
APP_NAME = "ai-image-forensics-bfree"
VOLUME_NAME = "bfree-weights"
SECRET_NAME = "bfree-endpoint"


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict


def _matches(presented: str | None, expected: str) -> bool:
    try:
        return bool(presented) and hmac.compare_digest(presented.encode("ascii"), expected.encode("ascii"))
    except (AttributeError, UnicodeError):
        return False


async def handle_score_request(
    *,
    presented_secret: str | None,
    content_length: str | None,
    chunks: AsyncIterator[bytes],
    expected_secret: str | None,
    get_scorer: Callable[[], object],
) -> Reply:
    request_id = uuid.uuid4().hex
    started = time.perf_counter()

    def finish(status: int, body: dict, device: str | None = None) -> Reply:
        print(json.dumps({
            "request_id": request_id, "status": status, "device": device,
            "duration_seconds": round(time.perf_counter() - started, 3),
        }), flush=True)
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
            return finish(413, {"error": "Image exceeds the 20 MiB limit."})
    if not data:
        return finish(400, {"error": "The request body is empty."})
    try:
        image, _source = decode_image(bytes(data))
    except ValueError as exc:
        return finish(400, {"error": str(exc)})
    try:
        scorer = get_scorer()
    except DetectorUnavailableError as exc:
        return finish(503, {"error": f"Remote scoring is unavailable: {exc}"})
    except Exception as exc:
        return finish(503, {"error": f"Remote scoring is unavailable: {type(exc).__name__}: {exc}"})
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(encode(image, "PNG"))
            path = Path(handle.name)
        try:
            raw = scorer.detect(path)
        except DetectorUnavailableError as exc:
            return finish(503, {"error": f"Remote scoring is unavailable: {exc}"})
        except Exception as exc:
            return finish(500, {"error": f"Scoring failed: {type(exc).__name__}: {exc}"})
        try:
            prediction = validate_prediction(raw)
        except DetectorUnavailableError as exc:
            reason = str(exc).removeprefix(ERROR_PREFIX)
            return finish(500, {"error": f"Scoring failed: the detector result is invalid: {reason}"})
        return finish(200, prediction, prediction["device"])
    except Exception as exc:
        return finish(500, {"error": f"Scoring failed: {type(exc).__name__}: {exc}"})
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checkpoint(weights_dir: Path, expected_sha256: str = BFREE_CHECKPOINT_SHA256) -> str:
    directory = Path(weights_dir).resolve()
    try:
        import yaml

        config = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
    except Exception as exc:
        raise DetectorUnavailableError(f"B-Free checkpoint configuration is unreadable: {exc}") from exc
    if not isinstance(config, dict) or not all(isinstance(config.get(key), str) for key in ("weights_file", "arch", "norm_type")):
        raise DetectorUnavailableError("B-Free config requires weights_file, arch, and norm_type strings.")
    checkpoint = (directory / config["weights_file"]).resolve()
    if not checkpoint.is_relative_to(directory):
        raise DetectorUnavailableError("B-Free checkpoint path escapes its weights directory.")
    if not checkpoint.is_file():
        raise DetectorUnavailableError("B-Free checkpoint file is missing.")
    digest = sha256_file(checkpoint)
    if digest != expected_sha256:
        raise DetectorUnavailableError(f"B-Free checkpoint SHA-256 mismatch, found {digest}.")
    return digest


def build_scorer() -> object:
    verify_checkpoint(WEIGHTS_DIR)
    detector = BFreeDetector(str(BFREE_REPO), str(WEIGHTS_DIR), "cuda")
    if detector.model_revision != BFREE_REVIEWED_REVISION:
        raise DetectorUnavailableError("B-Free checkout is not at the reviewed revision.")
    return detector


_SCORER = None
_SCORER_LOCK = threading.Lock()


def get_scorer() -> object:
    global _SCORER
    if _SCORER is None:
        with _SCORER_LOCK:
            if _SCORER is None:
                _SCORER = build_scorer()
    return _SCORER


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
    models = modal.Volume.from_name(VOLUME_NAME, create_if_missing=False)
    image = (
        modal.Image.from_registry("python:3.12", add_python="3.12")
        .apt_install("git")
        .pip_install(
            "torch==2.5.1", "torchvision==0.20.1", "timm==1.0.12", "transformers==4.43.4",
            "numpy==1.26.4", "Pillow", "PyYAML", "fastapi[standard]",
        )
        .run_commands(
            "git clone https://github.com/grip-unina/B-Free.git /opt/B-Free",
            f"git -C /opt/B-Free checkout {BFREE_REVIEWED_REVISION}",
        )
        .add_local_python_source("forensics")
    )

    @app.function(
        image=image,
        gpu="T4",
        max_containers=2,
        timeout=300,
        scaledown_window=300,
        volumes={str(MODELS_DIR): models.with_mount_options(read_only=True)},
        secrets=[modal.Secret.from_name(SECRET_NAME, required_keys=[SECRET_ENV])],
    )
    @modal.fastapi_endpoint(method="POST")
    async def score_endpoint(request: Request):
        reply = await handle_score_request(
            presented_secret=request.headers.get(SECRET_HEADER.lower()),
            content_length=request.headers.get("content-length"),
            chunks=request.stream(),
            expected_secret=os.environ.get(SECRET_ENV),
            get_scorer=get_scorer,
        )
        return JSONResponse(status_code=reply.status, content=reply.body)
