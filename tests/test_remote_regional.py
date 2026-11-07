import base64
import hashlib
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import unittest.mock

from PIL import Image

from forensics import remote_regional
from forensics.detectors import TRUFOR_REVIEWED_REVISION, DetectorUnavailableError, UnavailableDetector
from forensics.regional import publish_regional
from forensics.remote_regional import (
    ARTIFACT_NAMES_BY_KEY,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MODEL_NAME,
    REGIONAL_PREDICTION_KEYS,
    RemoteTruForRunner,
    choose_remote_regional,
    validate_regional_payload,
)


REVISION = "ae54475df6f41a491d7615100feb19263dec13f7"
SCALAR_KEYS = tuple(key for key in REGIONAL_PREDICTION_KEYS if key not in ARTIFACT_NAMES_BY_KEY)


def png_bytes(size=(32, 24), color="white", mode="RGB"):
    stream = io.BytesIO()
    Image.new(mode, size, color).save(stream, format="PNG")
    return stream.getvalue()


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def regional_payload(image_bytes):
    size = (32, 24)
    heatmap = png_bytes(size, "red")
    reliability = png_bytes(size, "black", "L")
    overlay = png_bytes(size, "blue")
    return {
        "status": "complete",
        "message": "TruFor generated a manipulation anomaly map and localization reliability map.",
        "warnings": ["TruFor localizes manipulation anomalies; it does not identify AI-generated pixels."],
        "model": MODEL_NAME,
        "model_revision": REVISION,
        "checkpoint_sha256": "a" * 64,
        "score": 0.71,
        "score_kind": "local_manipulation",
        "input_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "calibrated_probability": False,
        "device": "cuda",
        "runtime_seconds": 1.25,
        "imgsize": [size[1], size[0]],
        "heatmap_kind": "local_manipulation_anomaly",
        "heatmap_range": [0, 1],
        "heatmap_legend": "Fixed scale: blue 0 to red 1.",
        "reliability_legend": "Black 0 to white 1.",
        "reliability_mean": 0.42,
        "heatmap_base64": encoded(heatmap),
        "reliability_base64": encoded(reliability),
        "overlay_base64": encoded(overlay),
    }


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
            for name, value in self.server.extra_headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def log_message(self, *args):
        pass


class RemoteRegionalTests(unittest.TestCase):
    def setUp(self):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        self.httpd.requests = []
        self.httpd.extra_headers = {}
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/regional"
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "runs" / ("a" * 32)
        self.output.mkdir(parents=True)
        self.image = self.root / "sample.png"
        self.image.write_bytes(png_bytes())
        self.payload = regional_payload(self.image.read_bytes())
        self.httpd.script = (200, self.payload, 0)

    def runner(self, **kwargs):
        return RemoteTruForRunner(self.url, "s3cret", **kwargs)

    def assert_nothing_written(self):
        self.assertEqual([path.name for path in self.output.iterdir()], [])

    def test_valid_response_writes_the_three_artifacts(self):
        result = self.runner().run(self.image, self.output)

        self.assertEqual(
            set(result),
            set(SCALAR_KEYS) | {"input_name", "heatmap_path", "reliability_path", "overlay_path"},
        )
        self.assertNotIn("npz_path", result)
        self.assertNotIn("heatmap_base64", result)
        self.assertEqual(result["model"], MODEL_NAME)
        self.assertEqual(result["input_name"], "sample.png")
        self.assertIsInstance(result["score"], float)
        for name, filename in remote_regional.ARTIFACT_NAMES.items():
            path = Path(result[f"{name}_path"])
            self.assertTrue(path.is_absolute())
            self.assertEqual(path.name, filename)
            self.assertEqual(path.read_bytes(), base64.b64decode(self.payload[f"{name}_base64"]))
        request = self.httpd.requests[-1]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["headers"].get("x-trufor-secret"), "s3cret")
        self.assertEqual(request["headers"].get("content-type"), "application/octet-stream")
        self.assertEqual(request["body"], self.image.read_bytes())

    def test_publish_regional_turns_the_remote_record_into_urls(self):
        result = self.runner().run(self.image, self.output)
        record = publish_regional(result, self.output, "a" * 32, "regional-")

        for name in remote_regional.ARTIFACT_NAMES:
            self.assertEqual(
                (self.output / f"regional-{name}.png").read_bytes(),
                base64.b64decode(self.payload[f"{name}_base64"]),
            )
            self.assertEqual(record[f"{name}_url"], f"/runs/{'a' * 32}/regional-{name}.png")
        self.assertNotIn("_path", json.dumps(record))

    def test_rejected_secret_writes_no_file(self):
        self.httpd.script = (401, {"error": "Unauthorized."}, 0)

        with self.assertRaises(DetectorUnavailableError) as caught:
            self.runner().run(self.image, self.output)

        self.assertIn("HTTP 401", str(caught.exception))
        self.assertTrue(str(caught.exception).startswith("Remote TruFor unavailable: "))
        self.assert_nothing_written()

    def test_tampered_input_sha256_is_refused(self):
        payload = regional_payload(self.image.read_bytes())
        payload["input_sha256"] = "0" * 64
        self.httpd.script = (200, payload, 0)

        with self.assertRaises(DetectorUnavailableError) as caught:
            self.runner().run(self.image, self.output)

        self.assertIn("input_sha256", str(caught.exception))
        self.assert_nothing_written()

    def test_png_dimensions_must_match_imgsize(self):
        payload = regional_payload(self.image.read_bytes())
        payload["imgsize"] = [12, 16]
        self.httpd.script = (200, payload, 0)

        with self.assertRaises(DetectorUnavailableError) as caught:
            self.runner().run(self.image, self.output)

        self.assertIn("dimensions", str(caught.exception))
        self.assert_nothing_written()

    def test_contract_violations_never_yield_a_record(self):
        base = regional_payload(self.image.read_bytes())
        cases = {
            "extra key": ({**base, "note": "extra"}, "keys do not match"),
            "missing key": ({key: value for key, value in base.items() if key != "device"}, "keys do not match"),
            "wrong model": ({**base, "model": "TruFor"}, "model"),
            "wrong revision": ({**base, "model_revision": "0" * 40}, "model_revision"),
            "wrong score kind": ({**base, "score_kind": "ai_generation"}, "score_kind"),
            "score range": ({**base, "score": 1.5}, "score"),
            "bool score": ({**base, "score": True}, "score"),
            "nan reliability": ({**base, "reliability_mean": float("nan")}, "reliability_mean"),
            "mps device": ({**base, "device": "mps"}, "device"),
            "zero imgsize": ({**base, "imgsize": [0, 24]}, "imgsize"),
            "string imgsize": ({**base, "imgsize": ["24", "32"]}, "imgsize"),
            "bad base64": ({**base, "heatmap_base64": "!!!"}, "base64"),
            "jpeg artifact": ({**base, "heatmap_base64": encoded(jpeg_bytes())}, "PNG"),
        }
        for name, (payload, expected) in cases.items():
            with self.subTest(name=name):
                self.httpd.script = (200, payload, 0)
                with self.assertRaises(DetectorUnavailableError) as caught:
                    self.runner().run(self.image, self.output)
                self.assertIn(expected, str(caught.exception))
                self.assert_nothing_written()

    def test_only_http_200_carries_a_record(self):
        for status in (201, 202, 206):
            with self.subTest(status=status):
                self.httpd.script = (status, regional_payload(self.image.read_bytes()), 0)
                with self.assertRaises(DetectorUnavailableError) as caught:
                    self.runner().run(self.image, self.output)
                self.assertIn(f"HTTP {status}", str(caught.exception))
                self.assert_nothing_written()

    def test_redirect_is_refused_without_echoing_the_target(self):
        self.httpd.script = (302, regional_payload(self.image.read_bytes()), 0)
        self.httpd.extra_headers = {"Location": f"{self.url}?token=REVIEW_SECRET_ABC"}

        with self.assertRaises(DetectorUnavailableError) as caught:
            self.runner().run(self.image, self.output)

        self.assertIn("redirected", str(caught.exception))
        self.assertNotIn("REVIEW_SECRET_ABC", str(caught.exception))
        self.assert_nothing_written()

    def test_oversize_local_image_is_refused_without_a_request(self):
        with unittest.mock.patch.object(remote_regional, "MAX_BYTES", 10):
            with self.assertRaises(DetectorUnavailableError) as caught:
                self.runner().run(self.image, self.output)

        self.assertIn("byte limit", str(caught.exception))
        self.assertEqual(self.httpd.requests, [])
        self.assert_nothing_written()

    def test_oversize_response_is_refused(self):
        with unittest.mock.patch.object(remote_regional, "MAX_RESPONSE_BYTES", 100):
            with self.assertRaises(DetectorUnavailableError) as caught:
                self.runner().run(self.image, self.output)

        self.assertIn("larger than", str(caught.exception))
        self.assert_nothing_written()

    def test_malformed_json_is_refused(self):
        self.httpd.script = (200, b"{", 0)

        with self.assertRaises(DetectorUnavailableError) as caught:
            self.runner().run(self.image, self.output)

        self.assertIn("malformed JSON", str(caught.exception))
        self.assert_nothing_written()

    def test_timeout_names_the_cause(self):
        self.httpd.script = (200, regional_payload(self.image.read_bytes()), 2.0)
        started = time.perf_counter()

        with self.assertRaises(DetectorUnavailableError) as caught:
            self.runner(timeout=1).run(self.image, self.output)

        self.assertLess(time.perf_counter() - started, 3)
        self.assertIn("timed out", str(caught.exception))
        self.assert_nothing_written()

    def test_choose_remote_regional_builds_the_runner(self):
        runner = choose_remote_regional(self.url, "s3cret")

        self.assertIsInstance(runner, RemoteTruForRunner)
        self.assertTrue(runner.available)
        self.assertEqual(runner.status, "configured")
        self.assertEqual(runner.name, MODEL_NAME)
        self.assertIn("127.0.0.1", runner.reason)
        self.assertEqual(runner.run(self.image, self.output)["score"], 0.71)

    def test_misconfiguration_returns_unavailable_without_a_request(self):
        cases = {
            "missing url": ("", "s3cret"),
            "missing secret": (self.url, ""),
            "wrong scheme": (f"ftp://127.0.0.1:{self.httpd.server_port}/regional", "s3cret"),
            "credentials": (f"http://user:pass@127.0.0.1:{self.httpd.server_port}/regional", "s3cret"),
            "query": (self.url + "?run=1", "s3cret"),
            "non ascii secret": (self.url, "s\u00e9cret"),
        }
        for name, (url, secret) in cases.items():
            with self.subTest(name=name):
                runner = choose_remote_regional(url, secret)
                self.assertIsInstance(runner, UnavailableDetector)
                self.assertEqual(runner.name, MODEL_NAME)
                self.assertTrue(runner.reason.startswith("TruFor remote scoring is misconfigured:"))
                self.assertTrue(runner.reason.endswith("Unset TRUFOR_REMOTE_URL to run TruFor locally."))
        self.assertEqual(self.httpd.requests, [])

    def test_timeout_bounds(self):
        for value in ("x", "0", "3601", True, "12.5"):
            with self.subTest(value=value):
                runner = choose_remote_regional(self.url, "s3cret", value)
                self.assertIsInstance(runner, UnavailableDetector)
                self.assertIn("timeout", runner.reason)
        self.assertIsInstance(choose_remote_regional(self.url, "s3cret", "1200"), RemoteTruForRunner)
        self.assertEqual(self.httpd.requests, [])


class ValidationTests(unittest.TestCase):
    def test_pinned_constants(self):
        self.assertEqual(REVISION, TRUFOR_REVIEWED_REVISION)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, 1200)
        self.assertEqual(MAX_RESPONSE_BYTES, 160 * 1024 * 1024)
        self.assertEqual(remote_regional.SECRET_HEADER, "X-TruFor-Secret")
        self.assertEqual(len(REGIONAL_PREDICTION_KEYS), 21)
        self.assertNotIn("npz_path", REGIONAL_PREDICTION_KEYS)
        self.assertFalse([key for key in REGIONAL_PREDICTION_KEYS if key.endswith("_path")])

    def test_valid_payload_decodes_each_png_once(self):
        image = png_bytes()
        record = validate_regional_payload(regional_payload(image), hashlib.sha256(image).hexdigest())

        self.assertEqual(list(record), list(REGIONAL_PREDICTION_KEYS))
        for key in ARTIFACT_NAMES_BY_KEY:
            self.assertIsInstance(record[key], bytes)
        self.assertEqual(record["heatmap_base64"], base64.b64decode(regional_payload(image)["heatmap_base64"]))

    def test_extra_key_is_rejected(self):
        image = png_bytes()
        with self.assertRaises(DetectorUnavailableError):
            validate_regional_payload(
                {**regional_payload(image), "note": "extra"}, hashlib.sha256(image).hexdigest(),
            )


def jpeg_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="JPEG")
    return stream.getvalue()


if __name__ == "__main__":
    unittest.main()
