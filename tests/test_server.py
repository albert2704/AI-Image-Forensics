import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from PIL import Image

from forensics import server


def png_bytes(size=(32, 24), color="white"):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


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

    def test_trufor_status_matches_runner_resolution(self):
        root = Path(self.temp.name) / "TruFor"
        root.mkdir()
        (root / "test.py").write_text("")
        with unittest.mock.patch.dict(server.os.environ, {"TRUFOR_REPO": str(root)}):
            self.assertTrue(server.trufor_status()["available"])

    def test_publish_regional_strips_local_paths(self):
        from forensics.detectors import publish_regional
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


class ServerUnitTests(unittest.TestCase):
    def test_load_example_reports_missing_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            with unittest.mock.patch.object(server, "ROOT", Path(temporary)):
                with self.assertRaises(server.ExampleUnavailable):
                    server.load_example()


if __name__ == "__main__":
    unittest.main()
