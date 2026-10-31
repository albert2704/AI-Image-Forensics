import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from forensics import server


def png_bytes(size=(32, 24), color="white"):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def regional_payload(image_bytes, size=(32, 24)):
    payload = {
        "status": "complete",
        "message": "TruFor generated a manipulation anomaly map and localization reliability map.",
        "warnings": ["fixture"],
        "model": "TruFor (remote Modal)",
        "model_revision": "ae54475df6f41a491d7615100feb19263dec13f7",
        "checkpoint_sha256": "a" * 64,
        "score": .71,
        "score_kind": "local_manipulation",
        "input_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "calibrated_probability": False,
        "device": "cuda",
        "runtime_seconds": 1.25,
        "imgsize": [size[1], size[0]],
        "heatmap_kind": "local_manipulation_anomaly",
        "heatmap_range": [0, 1],
        "heatmap_legend": "fixture",
        "reliability_legend": "fixture",
        "reliability_mean": .42,
    }
    for name, color in (("heatmap", "red"), ("reliability", "black"), ("overlay", "blue")):
        payload[f"{name}_base64"] = base64.b64encode(png_bytes(size, color)).decode("ascii")
    return payload


class RegionalStubHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        with Image.open(io.BytesIO(body)) as image:
            width, height = image.size
        self.server.seen.append({
            "headers": {name.lower(): value for name, value in self.headers.items()},
            "body": body,
        })
        self.server.payload = regional_payload(body, (width, height))
        data = json.dumps(self.server.payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def write_run(directory, run_id, image_name="fixture.png"):
    directory.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "image": {"name": image_name, "width": 32, "height": 24, "bytes": 100},
        "config": {"quality": 90, "scale": .9, "rounds": 1, "mode": "cumulative"},
        "detector": {"name": "fixture", "status": "unavailable", "reason": ""},
        "variants": [],
        "summary": {"title": "fixture", "text": "fixture", "warnings": [], "flip_count": None},
        "regional": {"status": "not_requested", "message": "fixture"},
        "exports": {"json_url": f"/runs/{run_id}/report.json", "csv_url": f"/runs/{run_id}/measurements.csv"},
        "provenance": {},
    }
    (directory / "report.json").write_text(json.dumps(report))
    (directory / "source.bin").write_bytes(png_bytes())
    (directory / "original.png").write_bytes(png_bytes())
    return report


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.runs = root / "runs"
        self.examples = root / "examples"
        self.runs.mkdir()
        self.examples.mkdir()
        self.run_id = "a" * 32
        self.example_id = "b" * 32
        write_run(self.runs / self.run_id, self.run_id, "run.png")
        write_run(self.examples / self.example_id, self.example_id, "example.png")
        self.start_server()

    def start_server(self):
        server.Handler.detector = server.choose_detector({})
        server.Handler.planner = server.LocalPlanner()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.port = httpd.server_port

    def request(self, path, payload=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def get_json(self, path, payload=None):
        status, body = self.request(path, payload)
        return status, json.loads(body)

    def test_missing_example_returns_json_404(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "output").mkdir()
            (project / "output" / "verified-example.json").write_text(json.dumps({"run_id": "c" * 32}))
            with unittest.mock.patch.object(server, "ROOT", project), \
                 unittest.mock.patch.object(server, "RUNS", self.runs), \
                 unittest.mock.patch.object(server, "EXAMPLE_ROOT", self.examples):
                status, body = self.get_json("/api/example")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "The recorded example is not installed.")

    def test_example_resolves_from_committed_location(self):
        committed = json.loads((server.ROOT / "output" / "verified-example.json").read_text())["run_id"]
        with unittest.mock.patch.object(server, "RUNS", self.runs):
            status, body = self.get_json("/api/example")
        self.assertEqual(status, 200)
        self.assertEqual(body["report"]["run_id"], committed)
        self.assertEqual(body["filename"], body["report"]["image"]["name"])
        self.assertTrue(base64.b64decode(body["image_base64"]))

    def test_run_location_prefers_writable_runs(self):
        write_run(self.examples / self.run_id, self.run_id)
        with unittest.mock.patch.object(server, "RUNS", self.runs), \
             unittest.mock.patch.object(server, "EXAMPLE_ROOT", self.examples):
            location = server.run_location(self.run_id)
        self.assertTrue(location.writable)
        self.assertEqual(location.directory, self.runs / self.run_id)

    def test_example_artifacts_are_served(self):
        expected = (self.examples / self.example_id / "original.png").read_bytes()
        with unittest.mock.patch.object(server, "RUNS", self.runs), \
             unittest.mock.patch.object(server, "EXAMPLE_ROOT", self.examples):
            status, body = self.request(f"/runs/{self.example_id}/original.png")
        self.assertEqual(status, 200)
        self.assertEqual(body, expected)

    def test_recorded_example_rejects_regional_write(self):
        report_path = self.examples / self.example_id / "report.json"
        before = hashlib.sha256(report_path.read_bytes()).hexdigest()
        with unittest.mock.patch.object(server, "RUNS", self.runs), \
             unittest.mock.patch.object(server, "EXAMPLE_ROOT", self.examples):
            status, body = self.get_json("/api/regional", {"run_id": self.example_id})
        self.assertEqual(status, 409)
        self.assertIn("read-only", body["error"])
        self.assertEqual(hashlib.sha256(report_path.read_bytes()).hexdigest(), before)

    def test_investigate_rejects_ignored_threshold(self):
        payload = {"filename": "x.png", "image_base64": "aGk=", "budget": 4, "threshold": .9}
        status, body = self.get_json("/api/investigate", payload)
        self.assertEqual(status, 400)
        self.assertIn("0.5", body["error"])

    def test_regional_error_message_has_no_local_paths(self):
        directory = self.runs / self.run_id

        def failing(source, output, repo, executable, device="cpu"):
            raise RuntimeError(f"no usable result at {directory}/trufor-abc/inference.log")

        with unittest.mock.patch.object(server, "RUNS", self.runs), \
             unittest.mock.patch.object(server, "trufor_status", lambda: {"available": True, "reason": ""}), \
             unittest.mock.patch.object(server, "run_trufor", failing), \
             unittest.mock.patch.dict(server.os.environ, {"TRUFOR_REPO": "/nonexistent", "TRUFOR_REMOTE_URL": ""}):
            status, body = self.get_json("/api/regional", {"run_id": self.run_id})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "error")
        self.assertIn("the run directory", body["message"])
        self.assertNotIn(str(directory), json.dumps(body))
        stored = json.loads((directory / "report.json").read_text())
        self.assertNotIn(str(directory), json.dumps(stored))

    def test_trufor_status_matches_runner_resolution(self):
        root = Path(self.temp.name) / "TruFor"
        root.mkdir()
        (root / "test.py").write_text("")
        with unittest.mock.patch.dict(server.os.environ, {"TRUFOR_REPO": str(root)}):
            self.assertTrue(server.trufor_status()["available"])

    def test_trufor_status_expands_home(self):
        home = Path(self.temp.name) / "home"
        (home / "TruFor" / "TruFor_train_test").mkdir(parents=True)
        (home / "TruFor" / "TruFor_train_test" / "test.py").write_text("")
        with unittest.mock.patch.dict(server.os.environ, {"TRUFOR_REPO": "~/TruFor", "HOME": str(home)}):
            self.assertTrue(server.trufor_status()["available"])

    def test_publish_regional_strips_local_paths(self):
        from forensics.regional import publish_regional
        directory = self.examples / "publish"
        directory.mkdir()
        result = {"status": "complete", "score": .7, "message": "ok", "warnings": [],
                  "input_name": "/Users/example/secret.png", "npz_path": "/tmp/result.npz"}
        for name in ["heatmap", "reliability", "overlay"]:
            (directory / f"raw-{name}.png").write_bytes(png_bytes())
            result[f"{name}_path"] = str(directory / f"raw-{name}.png")
        record = publish_regional(result, directory, self.example_id, "regional-")
        self.assertEqual(record["heatmap_url"], f"/runs/{self.example_id}/regional-heatmap.png")
        self.assertTrue((directory / "regional-overlay.png").is_file())
        self.assertNotIn("_path", json.dumps(record))
        self.assertNotIn(str(directory), json.dumps(record))

    def test_trufor_status_names_the_remote_host(self):
        with unittest.mock.patch.dict(server.os.environ, {
            "TRUFOR_REMOTE_URL": "https://trufor.example.modal.run",
            "TRUFOR_REMOTE_SECRET": "s3cret",
            "TRUFOR_REMOTE_TIMEOUT": "",
        }, clear=False):
            status = server.trufor_status()

        self.assertTrue(status["available"])
        self.assertIn("trufor.example.modal.run", status["reason"])

    def test_trufor_status_reports_a_misconfigured_remote(self):
        with unittest.mock.patch.dict(server.os.environ, {
            "TRUFOR_REMOTE_URL": "https://trufor.example.modal.run",
            "TRUFOR_REMOTE_SECRET": "",
        }, clear=False):
            status = server.trufor_status()

        self.assertFalse(status["available"])
        self.assertTrue(status["reason"].startswith("TruFor remote scoring is misconfigured:"))

    def test_unset_remote_url_keeps_the_legacy_reason_and_no_import(self):
        saved = sys.modules.pop("forensics.remote_regional", None)
        if saved is not None:
            self.addCleanup(sys.modules.__setitem__, "forensics.remote_regional", saved)
        with unittest.mock.patch.dict(server.os.environ, {}, clear=True):
            status = server.trufor_status()

        self.assertEqual(status, {
            "available": False,
            "reason": "Set TRUFOR_REPO and install its pretrained model to enable regional evidence.",
        })
        self.assertNotIn("forensics.remote_regional", sys.modules)

    def test_regional_runs_the_remote_endpoint_and_publishes_pngs(self):
        stub = ThreadingHTTPServer(("127.0.0.1", 0), RegionalStubHandler)
        stub.seen = []
        stub.payload = None
        threading.Thread(target=stub.serve_forever, daemon=True).start()
        self.addCleanup(stub.server_close)
        self.addCleanup(stub.shutdown)
        directory = self.runs / self.run_id
        original = (directory / "original.png").read_bytes()

        def forbidden(*args, **kwargs):
            raise AssertionError("the local TruFor runner must not run")

        with unittest.mock.patch.object(server, "RUNS", self.runs), \
             unittest.mock.patch.dict(server.os.environ, {
                 "TRUFOR_REMOTE_URL": f"http://127.0.0.1:{stub.server_port}/regional",
                 "TRUFOR_REMOTE_SECRET": "s3cret",
                 "TRUFOR_REMOTE_TIMEOUT": "",
             }, clear=False), \
             unittest.mock.patch.object(server, "run_trufor", forbidden):
            status, body = self.get_json("/api/regional", {"run_id": self.run_id})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "complete")
        self.assertEqual(body["heatmap_url"], f"/runs/{self.run_id}/regional-heatmap.png")
        self.assertNotIn(str(directory), json.dumps(body))
        self.assertNotIn("_path", json.dumps(body))
        for name in ("heatmap", "reliability", "overlay"):
            self.assertEqual(
                (directory / f"regional-{name}.png").read_bytes(),
                base64.b64decode(stub.payload[f"{name}_base64"]),
            )
        self.assertEqual(stub.seen[-1]["headers"].get("x-trufor-secret"), "s3cret")
        self.assertEqual(stub.seen[-1]["headers"].get("content-type"), "application/octet-stream")
        self.assertEqual(stub.seen[-1]["body"], original)
        stored = json.loads((directory / "report.json").read_text())
        self.assertEqual(stored["regional"]["overlay_url"], f"/runs/{self.run_id}/regional-overlay.png")

    def test_regional_uses_the_local_runner_when_the_remote_url_is_unset(self):
        directory = self.runs / self.run_id
        calls = []

        def fake_run(source, output, repo, executable, device="cpu"):
            calls.append((source, output, repo, executable, device))
            result = {"status": "complete", "score": .5, "message": "local", "warnings": [],
                      "input_sha256": "x", "imgsize": [24, 32], "npz_path": "/tmp/result.npz"}
            for name in ("heatmap", "reliability", "overlay"):
                path = Path(output) / f"trufor-{name}.png"
                path.write_bytes(png_bytes())
                result[f"{name}_path"] = str(path)
            return result

        with unittest.mock.patch.object(server, "RUNS", self.runs), \
             unittest.mock.patch.object(server, "trufor_status", lambda: {"available": True, "reason": ""}), \
             unittest.mock.patch.object(server, "run_trufor", fake_run), \
             unittest.mock.patch.dict(server.os.environ, {"TRUFOR_REPO": "/nonexistent", "TRUFOR_REMOTE_URL": ""}):
            status, body = self.get_json("/api/regional", {"run_id": self.run_id})

        self.assertEqual(status, 200)
        self.assertEqual(calls, [(directory / "original.png", directory, "/nonexistent", "python3", "cpu")])
        self.assertTrue((directory / "regional-heatmap.png").is_file())
        self.assertEqual(body["overlay_url"], f"/runs/{self.run_id}/regional-overlay.png")

    def test_regional_reports_a_misconfigured_remote_as_unavailable(self):
        with unittest.mock.patch.object(server, "RUNS", self.runs), \
             unittest.mock.patch.dict(server.os.environ, {
                 "TRUFOR_REMOTE_URL": "https://trufor.example.modal.run",
                 "TRUFOR_REMOTE_SECRET": "",
             }, clear=False):
            status, body = self.get_json("/api/regional", {"run_id": self.run_id})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unavailable")
        self.assertTrue(body["message"].startswith("TruFor remote scoring is misconfigured:"))


class ServerUnitTests(unittest.TestCase):
    def test_load_example_reports_missing_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            with unittest.mock.patch.object(server, "ROOT", Path(temporary)):
                with self.assertRaises(server.ExampleUnavailable):
                    server.load_example()


if __name__ == "__main__":
    unittest.main()
