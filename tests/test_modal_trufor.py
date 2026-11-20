import asyncio
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import uuid

from PIL import Image

from forensics import detectors
from forensics.detectors import TRUFOR_REVIEWED_REVISION
from forensics.remote_regional import ARTIFACT_NAMES, MODEL_NAME, REGIONAL_PREDICTION_KEYS


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("modal_trufor", ROOT / "scripts" / "modal_trufor.py")
endpoint = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = endpoint
SPEC.loader.exec_module(endpoint)

REVISION = "ae54475df6f41a491d7615100feb19263dec13f7"
CHECKPOINT_SHA256 = "b" * 64


def png_bytes(size=(32, 24), color="white", mode="RGB"):
    stream = io.BytesIO()
    Image.new(mode, size, color).save(stream, format="PNG")
    return stream.getvalue()


class Chunks:
    def __init__(self, *chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class Untouchable:
    def __aiter__(self):
        raise AssertionError("the request body must not be read")


def forbidden_runner(*args):
    raise AssertionError("the runner must not be called")


class FakeRunner:
    def __init__(self, error=None, model="TruFor"):
        self.error = error
        self.model = model
        self.seen = []

    def __call__(self, source, output_dir):
        source = Path(source)
        self.seen.append(source.read_bytes())
        if self.error is not None:
            raise self.error
        with Image.open(source) as image:
            width, height = image.size
        run_dir = Path(output_dir) / ("trufor-" + uuid.uuid4().hex)
        run_dir.mkdir()
        result = {
            "status": "complete",
            "message": "TruFor generated a manipulation anomaly map and localization reliability map.",
            "warnings": ["TruFor localizes manipulation anomalies; it does not identify AI-generated pixels."],
            "model": self.model,
            "score": 0.71,
            "score_kind": "local_manipulation",
            "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "input_name": source.name,
            "calibrated_probability": False,
            "model_revision": REVISION,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "device": "cuda",
            "imgsize": [height, width],
            "runtime_seconds": 1.25,
            "heatmap_kind": "local_manipulation_anomaly",
            "heatmap_range": [0, 1],
            "heatmap_legend": "Fixed scale: blue 0 to red 1.",
            "reliability_legend": "Black 0 to white 1.",
            "reliability_mean": 0.42,
            "npz_path": str(run_dir / "result.npz"),
        }
        for name, filename in ARTIFACT_NAMES.items():
            path = run_dir / filename
            path.write_bytes(png_bytes((32, 24), mode=mode_for(name)))
            result[f"{name}_path"] = str(path)
        return result


def mode_for(name):
    return "L" if name == "reliability" else "RGB"


class EndpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)

    def request(self, **overrides):
        values = {
            "presented_secret": "s3cret",
            "content_length": None,
            "chunks": Chunks(png_bytes()),
            "expected_secret": "s3cret",
            "run_runner": FakeRunner(),
        }
        values.update(overrides)
        return asyncio.run(endpoint.handle_regional_request(**values))

    def test_module_imports_without_modal(self):
        self.assertIsNone(endpoint.modal)
        self.assertIsNone(endpoint.app)
        self.assertFalse(hasattr(endpoint, "image"))
        self.assertTrue(asyncio.iscoroutinefunction(endpoint.handle_regional_request))
        self.assertEqual(endpoint.MAX_UPLOAD_BYTES, 20 * 1024 * 1024)
        self.assertEqual(endpoint.SECRET_ENV, "TRUFOR_SHARED_SECRET")
        self.assertEqual(endpoint.SECRET_NAME, "trufor-endpoint")
        self.assertEqual(endpoint.APP_NAME, "ai-image-forensics-trufor")
        self.assertEqual(endpoint.TRUFOR_REPO, Path("/opt/TruFor"))
        self.assertEqual(endpoint.WEIGHTS_ZIP_MD5, "7bee48f3476c75616c3c5721ab256ff8")
        self.assertTrue(endpoint.WEIGHTS_URL.endswith("TruFor_weights.zip"))

    def test_both_scripts_import_with_modal_and_fastapi_absent(self):
        code = """
import runpy, sys
BLOCKED = {"modal", "fastapi", "torch"}

class Absent:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"No module named {fullname!r}")

sys.meta_path.insert(0, Absent())
module = runpy.run_path(sys.argv[1])
assert "modal" not in sys.modules
assert "fastapi" not in sys.modules
expect = sys.argv[2]
if expect == "none":
    assert module["app"] is None, module["app"]
else:
    assert "app" not in module
print("ok")
"""
        for name, expect in (("modal_trufor.py", "none"), ("modal_endpoint.py", "absent")):
            with self.subTest(script=name):
                completed = subprocess.run(
                    [sys.executable, "-c", code, str(ROOT / "scripts" / name), expect],
                    cwd=ROOT, capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), "ok")

    def test_missing_secret_returns_401_before_reading(self):
        reply = self.request(presented_secret=None, chunks=Untouchable(), run_runner=forbidden_runner)

        self.assertEqual(reply.status, 401)
        self.assertEqual(reply.body, {"error": "Unauthorized."})

    def test_wrong_secret_returns_401_before_reading(self):
        reply = self.request(presented_secret="wrong", chunks=Untouchable(), run_runner=forbidden_runner)

        self.assertEqual(reply.status, 401)
        self.assertEqual(reply.body, {"error": "Unauthorized."})

    def test_unset_server_secret_returns_503(self):
        for expected, presented in ((None, None), (None, ""), ("", "")):
            with self.subTest(expected=expected, presented=presented):
                reply = self.request(
                    expected_secret=expected, presented_secret=presented,
                    chunks=Untouchable(), run_runner=forbidden_runner,
                )
                self.assertEqual(reply.status, 503)
                self.assertEqual(reply.body, {"error": "Endpoint secret is not configured."})

    def test_declared_oversize_is_rejected_before_reading(self):
        reply = self.request(
            content_length=str(endpoint.MAX_UPLOAD_BYTES + 1), chunks=Untouchable(), run_runner=forbidden_runner,
        )

        self.assertEqual(reply.status, 413)
        self.assertEqual(reply.body, {"error": "Image exceeds the 20 MiB limit."})

    def test_invalid_content_length_is_rejected(self):
        for value in ("12x", "\u00b2", "9" * 5000):
            with self.subTest(value=value[:8]):
                reply = self.request(content_length=value, chunks=Untouchable(), run_runner=forbidden_runner)
                self.assertEqual(reply.status, 400)
                self.assertEqual(reply.body, {"error": "Invalid Content-Length."})

    def test_stream_oversize_stops_at_the_cap(self):
        with unittest.mock.patch.object(endpoint, "MAX_UPLOAD_BYTES", 1024):
            async def chunks():
                yield b"x" * 1025
                raise AssertionError("the endpoint read past the cap")

            reply = self.request(chunks=chunks(), run_runner=forbidden_runner)

        self.assertEqual(reply.status, 413)
        self.assertEqual(reply.body, {"error": "Image exceeds the 20 MiB limit."})

    def test_invalid_image_returns_400_without_a_runner(self):
        for body in (b"not an image at all", b""):
            with self.subTest(body=body[:4]):
                reply = self.request(chunks=Chunks(body), run_runner=forbidden_runner)
                self.assertEqual(reply.status, 400)
                self.assertEqual(set(reply.body), {"error"})

    def test_valid_image_returns_the_exact_key_set(self):
        runner = FakeRunner()
        reply = self.request(run_runner=runner)

        self.assertEqual(reply.status, 200)
        self.assertEqual(list(reply.body), list(REGIONAL_PREDICTION_KEYS))
        self.assertEqual(reply.body["model"], MODEL_NAME)
        self.assertEqual(reply.body["model_revision"], REVISION)
        self.assertEqual(reply.body["score"], 0.71)
        self.assertEqual(reply.body["input_sha256"], hashlib.sha256(png_bytes()).hexdigest())
        self.assertEqual(reply.body["imgsize"], [24, 32])
        self.assertNotIn("npz_path", reply.body)
        self.assertNotIn("input_name", reply.body)
        self.assertFalse([key for key in reply.body if key.endswith("_path")])
        for name in ARTIFACT_NAMES:
            self.assertEqual(
                base64.b64decode(reply.body[f"{name}_base64"]),
                png_bytes((32, 24), mode=mode_for(name)),
            )
        self.assertEqual(runner.seen, [png_bytes()])

    def test_runner_failure_returns_500_without_detail(self):
        for error in (RuntimeError(f"no result at {self.temp}/trufor-abc"), endpoint.DetectorUnavailableError("CUDA is not available")):
            with self.subTest(error=type(error).__name__):
                reply = self.request(run_runner=FakeRunner(error=error))
                self.assertEqual(reply.status, 500)
                self.assertEqual(reply.body, {"error": "Regional inference failed."})
                self.assertNotIn(str(self.temp), json.dumps(reply.body))

    def test_incomplete_runner_result_returns_500(self):
        def partial(source, output_dir):
            return {"status": "complete"}

        reply = self.request(run_runner=partial)

        self.assertEqual(reply.status, 500)
        self.assertEqual(reply.body, {"error": "Regional inference failed."})

    def test_a_jpeg_upload_reaches_the_runner_as_normalized_png(self):
        runner = FakeRunner()
        buffer = io.BytesIO()
        Image.new("RGB", (40, 30), (12, 90, 200)).save(buffer, format="JPEG", quality=90)
        uploaded = buffer.getvalue()

        reply = self.request(chunks=Chunks(uploaded), run_runner=runner)

        self.assertEqual(reply.status, 200)
        seen = runner.seen[0]
        self.assertTrue(seen.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(seen)) as image:
            self.assertEqual(image.size, (40, 30))
        self.assertEqual(reply.body["input_sha256"], hashlib.sha256(uploaded).hexdigest())

    def test_verify_layout_accepts_the_reviewed_checkout(self):
        repo = self.write_repo()
        digest = hashlib.sha256((repo / endpoint.CHECKPOINT).read_bytes()).hexdigest()
        with unittest.mock.patch.object(endpoint, "_revision", lambda root: REVISION), \
                unittest.mock.patch.object(endpoint, "CHECKPOINT_SHA256", digest):
            matched = endpoint.verify_layout(repo)

        self.assertEqual(matched, digest)

    def test_verify_layout_rejects_a_checkpoint_that_is_not_pinned(self):
        repo = self.write_repo()
        with unittest.mock.patch.object(endpoint, "_revision", lambda root: REVISION), \
                self.assertRaises(endpoint.DetectorUnavailableError) as caught:
            endpoint.verify_layout(repo)

        self.assertIn("not the pinned", str(caught.exception))

    def test_verify_layout_rejects_missing_files_or_a_foreign_revision(self):
        cases = {"missing entry": self.write_repo(entry=False), "missing checkpoint": self.write_repo(checkpoint=False)}
        for name, repo in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(endpoint.DetectorUnavailableError):
                    endpoint.verify_layout(repo)
        repo = self.write_repo()
        with unittest.mock.patch.object(endpoint, "_revision", lambda root: "0" * 40):
            with self.assertRaises(endpoint.DetectorUnavailableError) as caught:
                endpoint.verify_layout(repo)
        self.assertIn("revision", str(caught.exception))

    def test_build_run_runner_binds_the_reviewed_arguments(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))
            return {"status": "complete"}

        with unittest.mock.patch.object(detectors, "run_trufor", fake_run):
            result = endpoint.build_run_runner()(Path("input.png"), Path("out"))

        self.assertEqual(result, {"status": "complete"})
        self.assertEqual(
            calls,
            [((Path("input.png"), Path("out"), endpoint.TRUFOR_REPO, sys.executable, "cuda"), {})],
        )

    def write_repo(self, entry=True, checkpoint=True):
        repo = self.temp / f"repo-{uuid.uuid4().hex}"
        (repo / "TruFor_train_test" / "pretrained_models").mkdir(parents=True)
        if entry:
            (repo / "TruFor_train_test" / "test.py").write_text("")
        if checkpoint:
            (repo / endpoint.CHECKPOINT).write_bytes(b"checkpoint fixture")
        return repo


class ConstantTests(unittest.TestCase):
    def test_revision_matches_the_reviewed_constant(self):
        self.assertEqual(REVISION, TRUFOR_REVIEWED_REVISION)
        self.assertEqual(len(REGIONAL_PREDICTION_KEYS), 21)


if __name__ == "__main__":
    unittest.main()
