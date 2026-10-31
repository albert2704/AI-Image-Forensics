import http.server
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

from PIL import Image

from forensics import detectors
from forensics.detectors import DetectorUnavailableError, UnavailableDetector
from forensics.remote import BFREE_CHECKPOINT_SHA256, RemoteBFreeDetector, choose_remote_detector, validate_prediction


REVISION = "c6a9f898782fb466b29af01f21960b67415afb0e"
CHECKPOINT = "5948ca78f4d94e820c250d24cdf155035b4a85960443800bfe6bb7f06bffe947"
PREDICTION = {
    "score": 0.9882320210699883,
    "raw_logit": 4.430535316467285,
    "score_kind": "ai_generation",
    "model": "B-Free",
    "model_revision": REVISION,
    "checkpoint_sha256": CHECKPOINT,
    "device": "cuda",
    "runtime_seconds": 0.28,
    "calibrated_probability": False,
}
LEGACY_REASON = "Set BFREE_REPO and install the official B-Free checkpoint to enable AI scoring."


def png_bytes(size=(32, 24)):
    stream = io.BytesIO()
    Image.new("RGB", size, "white").save(stream, format="PNG")
    return stream.getvalue()


class StubHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.requests.append({
            "method": self.command,
            "path": self.path,
            "headers": {name.lower(): value for name, value in self.headers.items()},
            "body": body,
        })
        status, payload, delay = self.server.script
        if delay:
            time.sleep(delay)
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def log_message(self, *args):
        pass


class RemoteDetectorTests(unittest.TestCase):
    def setUp(self):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        self.httpd.requests = []
        self.httpd.script = (200, PREDICTION, 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/score"
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.image = Path(temporary.name) / "sample.png"
        self.image.write_bytes(png_bytes())

    def test_valid_response_becomes_the_shared_evidence_shape(self):
        result = RemoteBFreeDetector(self.url, "s3cret").detect(self.image)

        self.assertEqual(list(result), list(PREDICTION))
        self.assertEqual(result, PREDICTION)
        self.assertIsInstance(result["score"], float)
        self.assertIsInstance(result["raw_logit"], float)
        request = self.httpd.requests[-1]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["headers"].get("x-bfree-secret"), "s3cret")
        self.assertEqual(request["headers"].get("content-type"), "application/octet-stream")
        self.assertEqual(request["body"], self.image.read_bytes())

    def test_unauthorized_response_names_the_status(self):
        self.httpd.script = (401, {"error": "Unauthorized."}, 0)

        with self.assertRaises(DetectorUnavailableError) as caught:
            RemoteBFreeDetector(self.url, "s3cret").detect(self.image)

        self.assertIn("HTTP 401", str(caught.exception))
        self.assertTrue(str(caught.exception).startswith("Remote B-Free unavailable: "))

    def test_bad_responses_never_yield_a_score(self):
        missing = {key: value for key, value in PREDICTION.items() if key != "device"}
        cases = {
            "http 500": (500, {"error": "boom"}, "HTTP 500"),
            "malformed json": (200, b"{", "malformed JSON"),
            "not an object": (200, [], "not a JSON object"),
            "missing key": (200, missing, "keys do not match"),
            "wrong checkpoint": (200, {**PREDICTION, "checkpoint_sha256": "0" * 64}, "checkpoint_sha256"),
            "bool score": (200, {**PREDICTION, "score": True}, "score"),
            "nan score": (200, {**PREDICTION, "score": float("nan")}, "score"),
            "out of range score": (200, {**PREDICTION, "score": 1.5}, "score"),
        }
        for name, (status, payload, expected) in cases.items():
            with self.subTest(name=name):
                self.httpd.script = (status, payload, 0)
                with self.assertRaises(DetectorUnavailableError) as caught:
                    RemoteBFreeDetector(self.url, "s3cret").detect(self.image)
                self.assertIn(expected, str(caught.exception))

    def test_timeout_names_the_cause(self):
        self.httpd.script = (200, PREDICTION, 2.0)
        started = time.perf_counter()

        with self.assertRaises(DetectorUnavailableError) as caught:
            RemoteBFreeDetector(self.url, "s3cret", timeout=1).detect(self.image)

        self.assertLess(time.perf_counter() - started, 3)
        self.assertIn("timed out", str(caught.exception))

    def test_misconfiguration_returns_unavailable_without_a_request(self):
        cases = {
            "missing secret": (self.url, ""),
            "wrong scheme": (f"ftp://127.0.0.1:{self.httpd.server_port}/score", "s3cret"),
            "credentials": (f"http://user:pass@127.0.0.1:{self.httpd.server_port}/score", "s3cret"),
            "non ascii secret": (self.url, "s\u00e9cret"),
            "query": (self.url + "?run=1", "s3cret"),
        }
        for name, (url, secret) in cases.items():
            with self.subTest(name=name):
                detector = choose_remote_detector(url, secret)
                self.assertIsInstance(detector, UnavailableDetector)
                self.assertTrue(detector.reason.startswith("B-Free remote scoring is misconfigured:"))
                self.assertTrue(detector.reason.endswith("Unset BFREE_REMOTE_URL to score locally."))
        self.assertEqual(self.httpd.requests, [])

    def test_choose_detector_returns_the_remote_adapter(self):
        with unittest.mock.patch.dict(os.environ, {"BFREE_REPO": "", "BFREE_REMOTE_TIMEOUT": ""}, clear=False):
            detector = detectors.choose_detector({"BFREE_REMOTE_URL": self.url, "BFREE_REMOTE_SECRET": "s3cret"})

        self.assertIsInstance(detector, RemoteBFreeDetector)
        self.assertTrue(detector.available)
        self.assertEqual(detector.detect(self.image)["score"], PREDICTION["score"])
        self.assertEqual(self.httpd.requests[-1]["headers"].get("x-bfree-secret"), "s3cret")

    def test_environment_url_selects_the_remote_adapter(self):
        with unittest.mock.patch.dict(
            os.environ,
            {"BFREE_REMOTE_URL": self.url, "BFREE_REMOTE_SECRET": "s3cret", "BFREE_REMOTE_TIMEOUT": ""},
            clear=False,
        ):
            detector = detectors.choose_detector({})

        self.assertIsInstance(detector, RemoteBFreeDetector)
        self.assertEqual(detector.detect(self.image)["score"], PREDICTION["score"])

    def test_unset_remote_url_keeps_the_legacy_reason_and_no_import(self):
        self.drop_remote_module()
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            detector = detectors.choose_detector({})

        self.assertIsInstance(detector, UnavailableDetector)
        self.assertEqual(detector.reason, LEGACY_REASON)
        self.assertNotIn("forensics.remote", sys.modules)

    def test_empty_remote_url_behaves_as_unset(self):
        self.drop_remote_module()
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            detector = detectors.choose_detector({"BFREE_REMOTE_URL": ""})

        self.assertIsInstance(detector, UnavailableDetector)
        self.assertEqual(detector.reason, LEGACY_REASON)
        self.assertNotIn("forensics.remote", sys.modules)

    def drop_remote_module(self):
        saved = sys.modules.pop("forensics.remote", None)
        if saved is not None:
            self.addCleanup(sys.modules.__setitem__, "forensics.remote", saved)


class ValidationTests(unittest.TestCase):
    def test_pinned_constants_match_the_measured_identity(self):
        self.assertEqual(BFREE_CHECKPOINT_SHA256, CHECKPOINT)
        self.assertEqual(PREDICTION["model_revision"], detectors.BFREE_REVIEWED_REVISION)

    def test_extra_key_is_rejected(self):
        with self.assertRaises(DetectorUnavailableError):
            validate_prediction({**PREDICTION, "note": "extra"})


if __name__ == "__main__":
    unittest.main()
