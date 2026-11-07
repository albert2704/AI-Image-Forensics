"""Opt-in remote B-Free scoring through an authenticated Modal endpoint.

The endpoint returns the same evidence shape as the local adapter. Every
transport, HTTP, JSON, and contract failure raises an explicit error, so a
missing score never becomes zero.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from .detectors import BFREE_REVIEWED_REVISION, DetectorUnavailableError, UnavailableDetector
from .pipeline import MAX_BYTES


BFREE_CHECKPOINT_SHA256 = "5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947"
SECRET_HEADER = "X-BFree-Secret"
DEFAULT_TIMEOUT_SECONDS = 180
MAX_RESPONSE_BYTES = 64 * 1024

PREDICTION_KEYS = (
    "score", "raw_logit", "score_kind", "model", "model_revision",
    "checkpoint_sha256", "device", "runtime_seconds", "calibrated_probability",
)
DEVICE_PATTERN = re.compile(r"(?:cpu|cuda(?::[0-9]+)?)\Z")
ERROR_PREFIX = "Remote B-Free unavailable: "
MISCONFIGURED_PREFIX = "B-Free remote scoring is misconfigured: "


def _unavailable(reason: str) -> DetectorUnavailableError:
    return DetectorUnavailableError(ERROR_PREFIX + reason)


def _number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_prediction(payload: object) -> dict:
    """Parse a remote payload at the boundary. Never return a partial result."""
    if not isinstance(payload, dict):
        raise _unavailable("the response is not a JSON object.")
    missing = [key for key in PREDICTION_KEYS if key not in payload]
    extra = [key for key in payload if key not in PREDICTION_KEYS]
    if missing or extra:
        raise _unavailable(f"the response keys do not match the contract (missing {missing}, unexpected {extra}).")
    if not _number(payload["score"]) or not 0 <= payload["score"] <= 1:
        raise _unavailable("score must be a finite number between 0 and 1.")
    if not _number(payload["raw_logit"]):
        raise _unavailable("raw_logit must be a finite number.")
    if payload["score_kind"] != "ai_generation":
        raise _unavailable("score_kind must be ai_generation.")
    if payload["model"] != "B-Free":
        raise _unavailable("model must be B-Free.")
    if payload["model_revision"] != BFREE_REVIEWED_REVISION:
        raise _unavailable("model_revision is not the reviewed B-Free revision.")
    if payload["checkpoint_sha256"] != BFREE_CHECKPOINT_SHA256:
        raise _unavailable("checkpoint_sha256 is not the verified checkpoint.")
    if not isinstance(payload["device"], str) or not DEVICE_PATTERN.match(payload["device"]):
        raise _unavailable("device must be cpu, cuda, or cuda:N.")
    if not _number(payload["runtime_seconds"]) or payload["runtime_seconds"] < 0:
        raise _unavailable("runtime_seconds must be a finite number of at least 0.")
    if payload["calibrated_probability"] is not False:
        raise _unavailable("calibrated_probability must be false.")
    return {
        "score": float(payload["score"]),
        "raw_logit": float(payload["raw_logit"]),
        "score_kind": payload["score_kind"],
        "model": payload["model"],
        "model_revision": payload["model_revision"],
        "checkpoint_sha256": payload["checkpoint_sha256"],
        "device": payload["device"],
        "runtime_seconds": payload["runtime_seconds"],
        "calibrated_probability": False,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        # The target is server-controlled. Keeping it out of the message keeps it
        # out of report.json, where a reflected secret would otherwise persist.
        raise _unavailable("the endpoint redirected to another address, which is refused.")


class RemoteBFreeDetector:
    """Score through the Modal endpoint. The upload leaves this machine."""

    available = True
    status = "configured"
    name = "B-Free (remote Modal)"

    def __init__(self, url: str, secret: str, timeout: int = DEFAULT_TIMEOUT_SECONDS, opener=None):
        self._url = url
        self._secret = secret
        self._timeout = timeout
        self._opener = opener or urllib.request.build_opener(_NoRedirect())
        host = urllib.parse.urlsplit(url).hostname or url
        self.reason = f"Scoring runs on the Modal host {host}. Uploaded images and their variants leave this machine."

    def detect(self, image_path: Path) -> dict:
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
            # urllib can reject a malformed request before any socket work, for example with InvalidURL.
            raise _unavailable(f"the request failed: {type(exc).__name__}: {exc}") from None
        if status != 200:
            raise _unavailable(f"the endpoint returned HTTP {status} instead of 200.")
        if len(body) > MAX_RESPONSE_BYTES:
            raise _unavailable(f"the response is larger than {MAX_RESPONSE_BYTES} bytes.")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise _unavailable(f"the response is malformed JSON: {exc}") from None
        return validate_prediction(payload)


def _url_problem(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(url)
        parsed.port  # Reading .port raises ValueError for a malformed port.
    except ValueError:
        return "the endpoint URL is not a valid URL"
    if not parsed.scheme or not parsed.hostname:
        return "the endpoint URL must be absolute and include a host"
    if parsed.username is not None or parsed.password is not None:
        return "the endpoint URL must not embed credentials"
    if parsed.query or parsed.fragment:
        return "the endpoint URL must not include a query or fragment"
    if parsed.scheme == "https":
        return None
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return None
    return "the endpoint URL must use https unless it points at loopback"


def _secret_problem(secret: object) -> str | None:
    if not isinstance(secret, str) or not secret:
        return "the shared secret is missing"
    if len(secret) > 512:
        return "the shared secret is longer than 512 characters"
    try:
        secret.encode("ascii")
    except UnicodeError:
        return "the shared secret must be ASCII"
    if any(ord(character) < 32 or ord(character) == 127 for character in secret):
        return "the shared secret must not contain control characters"
    return None


def choose_remote_detector(url, secret, timeout=None) -> RemoteBFreeDetector | UnavailableDetector:
    """Build the remote adapter or an explicit unavailable state. Never raises."""
    if not isinstance(url, str) or not url:
        return UnavailableDetector(MISCONFIGURED_PREFIX + "the endpoint URL is missing. Unset BFREE_REMOTE_URL to score locally.")
    problem = _url_problem(url) or _secret_problem(secret)
    if problem:
        return UnavailableDetector(f"{MISCONFIGURED_PREFIX}{problem}. Unset BFREE_REMOTE_URL to score locally.")
    if timeout is None or timeout == "":
        seconds = DEFAULT_TIMEOUT_SECONDS
    else:
        try:
            seconds = int(timeout)
        except (TypeError, ValueError):
            seconds = 0
        if isinstance(timeout, bool) or not 1 <= seconds <= 900:
            return UnavailableDetector(
                f"{MISCONFIGURED_PREFIX}the timeout must be an integer from 1 to 900 seconds. "
                "Unset BFREE_REMOTE_URL to score locally."
            )
    return RemoteBFreeDetector(url, secret, seconds)
