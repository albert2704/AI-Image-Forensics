"""Opt-in remote TruFor localization through an authenticated Modal endpoint.

The endpoint returns the same regional evidence as the local adapter, with the
three PNGs inline instead of filesystem paths. Every transport, HTTP, JSON, and
contract failure raises an explicit error, so a missing map never becomes an
empty one.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import math
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PIL import Image

from .detectors import TRUFOR_REVIEWED_REVISION, DetectorUnavailableError, UnavailableDetector
from .pipeline import MAX_BYTES
from .remote import DEVICE_PATTERN, _NoRedirect, _secret_problem, _url_problem


SECRET_HEADER = "X-TruFor-Secret"
DEFAULT_TIMEOUT_SECONDS = 1200
MAX_RESPONSE_BYTES = 160 * 1024 * 1024
ERROR_PREFIX = "Remote TruFor unavailable: "
MISCONFIGURED_PREFIX = "TruFor remote scoring is misconfigured: "
MODEL_NAME = "TruFor (remote Modal)"

ARTIFACT_NAMES = {
    "heatmap": "localization-heatmap.png",
    "reliability": "localization-reliability.png",
    "overlay": "localization-overlay.png",
}
ARTIFACT_NAMES_BY_KEY = {f"{name}_base64": filename for name, filename in ARTIFACT_NAMES.items()}

# The exact wire contract. The endpoint builds its reply in this order and the
# client refuses anything else.
REGIONAL_PREDICTION_KEYS = (
    "status", "message", "warnings", "model", "model_revision",
    "checkpoint_sha256", "score", "score_kind", "input_sha256",
    "calibrated_probability", "device", "runtime_seconds", "imgsize",
    "heatmap_kind", "heatmap_range", "heatmap_legend", "reliability_legend",
    "reliability_mean", "heatmap_base64", "reliability_base64", "overlay_base64",
)


def _unavailable(reason: str) -> DetectorUnavailableError:
    return DetectorUnavailableError(ERROR_PREFIX + reason)


def _number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _png(value, imgsize, label: str) -> bytes:
    if not isinstance(value, str):
        raise _unavailable(f"{label} must be a base64 string.")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise _unavailable(f"{label} is not valid base64.") from None
    if not data:
        raise _unavailable(f"{label} is empty.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
                raise _unavailable(f"{label} must be a single-frame PNG.")
            if image.size != (imgsize[1], imgsize[0]):
                raise _unavailable(f"{label} dimensions do not match imgsize.")
            image.load()
    except DetectorUnavailableError:
        raise
    except (OSError, SyntaxError, ValueError):
        raise _unavailable(f"{label} is not a decodable PNG.") from None
    return data


def validate_regional_payload(payload: object, input_sha256: str) -> dict:
    """Parse a remote payload at the boundary. Never return a partial result.

    The three PNG keys carry their decoded bytes so a caller decodes each image
    once. Every other key carries its validated wire value.
    """
    if not isinstance(payload, dict):
        raise _unavailable("the response is not a JSON object.")
    missing = [key for key in REGIONAL_PREDICTION_KEYS if key not in payload]
    extra = [key for key in payload if key not in REGIONAL_PREDICTION_KEYS]
    if missing or extra:
        raise _unavailable(f"the response keys do not match the contract (missing {missing}, unexpected {extra}).")
    if not _number(payload["score"]) or not 0 <= payload["score"] <= 1:
        raise _unavailable("score must be a finite number between 0 and 1.")
    if payload["score_kind"] != "local_manipulation":
        raise _unavailable("score_kind must be local_manipulation.")
    if payload["model"] != MODEL_NAME:
        raise _unavailable(f"model must be {MODEL_NAME}.")
    if payload["model_revision"] != TRUFOR_REVIEWED_REVISION:
        raise _unavailable("model_revision is not the reviewed TruFor revision.")
    if not isinstance(payload["device"], str) or not DEVICE_PATTERN.match(payload["device"]):
        raise _unavailable("device must be cpu, cuda, or cuda:N.")
    imgsize = payload["imgsize"]
    if not isinstance(imgsize, list) or len(imgsize) != 2 or not all(
        isinstance(side, int) and not isinstance(side, bool) and side > 0 for side in imgsize
    ):
        raise _unavailable("imgsize must be a list of two positive integers.")
    if not isinstance(input_sha256, str) or payload["input_sha256"] != input_sha256:
        raise _unavailable("input_sha256 does not match the image that was sent.")
    if not _number(payload["reliability_mean"]) or not 0 <= payload["reliability_mean"] <= 1:
        raise _unavailable("reliability_mean must be a finite number between 0 and 1.")
    record = {}
    for key in REGIONAL_PREDICTION_KEYS:
        if key in ARTIFACT_NAMES_BY_KEY:
            record[key] = _png(payload[key], imgsize, ARTIFACT_NAMES_BY_KEY[key])
        elif key in {"score", "reliability_mean"}:
            record[key] = float(payload[key])
        else:
            record[key] = payload[key]
    return record


class RemoteTruForRunner:
    """Run regional localization through the Modal endpoint. The upload leaves this machine."""

    available = True
    status = "configured"
    name = MODEL_NAME

    def __init__(self, url: str, secret: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS, opener=None):
        self._url = url
        self._secret = secret
        self._timeout = timeout
        self._opener = opener or urllib.request.build_opener(_NoRedirect())
        host = urllib.parse.urlsplit(url).hostname or url
        self.reason = f"Regional inference runs on the Modal host {host}. Uploaded images leave this machine."

    def run(self, image_path: Path, directory) -> dict:
        path = Path(image_path)
        try:
            size = path.stat().st_size
            if size > MAX_BYTES:
                raise _unavailable(f"the image is {size} bytes, over the {MAX_BYTES} byte limit.")
            data = path.read_bytes()
        except OSError as exc:
            raise _unavailable(f"the image could not be read: {exc}") from None
        if not data:
            raise _unavailable("the image file is empty.")
        request = urllib.request.Request(
            self._url, data=data, method="POST",
            headers={"Content-Type": "application/octet-stream", SECRET_HEADER: self._secret},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                status = response.status
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except DetectorUnavailableError:
            raise
        except urllib.error.HTTPError as exc:
            exc.close()
            raise _unavailable(f"the endpoint returned HTTP {exc.code}.") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise _unavailable(f"the request timed out after {self._timeout} seconds.") from None
            raise _unavailable(f"the connection failed: {exc.reason}") from None
        except TimeoutError:
            raise _unavailable(f"the request timed out after {self._timeout} seconds.") from None
        except OSError as exc:
            raise _unavailable(f"the connection failed: {exc}") from None
        except Exception as exc:
            # urllib can reject a malformed request before any socket work.
            raise _unavailable(f"the request failed: {type(exc).__name__}: {exc}") from None
        if status != 200:
            raise _unavailable(f"the endpoint returned HTTP {status} instead of 200.")
        if len(body) > MAX_RESPONSE_BYTES:
            raise _unavailable(f"the response is larger than {MAX_RESPONSE_BYTES} bytes.")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise _unavailable(f"the response is malformed JSON: {exc}") from None
        record = validate_regional_payload(payload, hashlib.sha256(data).hexdigest())
        try:
            run_dir = Path(directory).expanduser().resolve() / ("trufor-remote-" + uuid.uuid4().hex)
            run_dir.mkdir(parents=True, exist_ok=False)
            for name, filename in ARTIFACT_NAMES.items():
                target = run_dir / filename
                target.write_bytes(record.pop(f"{name}_base64"))
                record[f"{name}_path"] = str(target)
        except OSError as exc:
            raise _unavailable(f"the regional artifacts could not be written: {exc}") from None
        record["input_name"] = path.name
        return record


def choose_remote_regional(url, secret, timeout=None) -> RemoteTruForRunner | UnavailableDetector:
    """Build the remote regional runner or an explicit unavailable state. Never raises."""
    if not isinstance(url, str) or not url:
        return UnavailableDetector(
            MISCONFIGURED_PREFIX
            + "the endpoint URL is missing. Unset TRUFOR_REMOTE_URL to run TruFor locally.",
            name=MODEL_NAME,
        )
    problem = _url_problem(url) or _secret_problem(secret)
    if problem:
        return UnavailableDetector(
            f"{MISCONFIGURED_PREFIX}{problem}. Unset TRUFOR_REMOTE_URL to run TruFor locally.",
            name=MODEL_NAME,
        )
    if timeout is None or timeout == "":
        seconds = DEFAULT_TIMEOUT_SECONDS
    else:
        try:
            seconds = int(timeout)
        except (TypeError, ValueError):
            seconds = 0
        if isinstance(timeout, bool) or not 1 <= seconds <= 3600:
            return UnavailableDetector(
                f"{MISCONFIGURED_PREFIX}the timeout must be an integer from 1 to 3600 seconds. "
                "Unset TRUFOR_REMOTE_URL to run TruFor locally.",
                name=MODEL_NAME,
            )
    return RemoteTruForRunner(url, secret, timeout=seconds)
